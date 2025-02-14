import itertools
from pathlib import Path

import einops as ein
import numpy as np
import pandas as pd

from utils import models, preprocessing, exports
from utils.preprocessing import downsample_terr_dfs

cwd = Path.cwd()
husky_csv_dir = cwd / "data" / "borealtc"
vulpi_csv_dir = cwd / "data" / "vulpi"

results_dir = cwd / "results" / "split"
results_dir.mkdir(parents=True, exist_ok=True)

RANDOM_STATE = 21

# Define channels
columns = {
    "imu": {
        "wx": True,
        "wy": True,
        "wz": True,
        "ax": True,
        "ay": True,
        "az": True,
    },
    "pro": {
        "velL": True,
        "velR": True,
        "curL": True,
        "curR": True,
    },
}
summary_husky = pd.DataFrame({"columns": pd.Series(columns)})
summary_vulpi = pd.DataFrame({"columns": pd.Series(columns)})

# Get recordings
husky_terr_dfs = preprocessing.get_recordings(husky_csv_dir, summary_husky)
vulpi_terr_dfs = preprocessing.get_recordings(vulpi_csv_dir, summary_vulpi)

husky_terr_dfs, vulpi_terr_dfs = downsample_terr_dfs(
    husky_terr_dfs, summary_husky, vulpi_terr_dfs, summary_vulpi
)
terr_dfs, summary = preprocessing.merge_terr_dfs(
    husky_terr_dfs, summary_husky, vulpi_terr_dfs, summary_vulpi
)
DATASET = "CONCAT"

# Set data partition parameters
NUM_CLASSES = len(np.unique(terr_dfs["imu"].terrain))
N_FOLDS = 5
PART_WINDOW = 5  # seconds
# MOVING_WINDOWS = [1.5, 1.6, 1.7, 1.8]  # seconds
MOVING_WINDOWS = [1.7]  # seconds

# Data partition and sample extraction
train, test = preprocessing.partition_data(
    terr_dfs, summary, PART_WINDOW, N_FOLDS, random_state=RANDOM_STATE, ablation=True
)

num_splits = len(train[0])
train_sizes = [train[0][i]["pro"].shape[0] for i in range(num_splits)]
with exports.JSONExporter("analysis/figs/train-sizes.json") as data:
    data["train_sizes"] = train_sizes

merged = preprocessing.merge_upsample(terr_dfs, summary, mode="last")

# Data augmentation parameters
# 0 < STRIDE < MOVING_WINDOWS
STRIDE = 0.1  # seconds
# If True, balance the classes while augmenting
# If False, imbalance the classes while augmenting
HOMOGENEOUS_AUGMENTATION = True

# CNN parameters
cnn_par = {
    "num_classes": NUM_CLASSES,
    "time_window": 0.4,
    "time_overlap": 0.2,
    "filter_size": [3, 3],
    "num_filters": 16,
}

cnn_train_opt = {
    "hamming": True,
    "valid_perc": 0.1,
    "init_learn_rate": 0.005,
    "learn_drop_factor": 0.1,
    "max_epochs": 150,
    "minibatch_size": 10,
    "valid_patience": 8,
    "scheduler": "plateau",  # "plateau" or "reduce_lr_on_plateau
    "reduce_lr_patience": 4,
    "valid_frequency": 1.0,
    "gradient_threshold": 6,  # None to disable
    "focal_loss": False,
    "focal_loss_alpha": 0.25,
    "focal_loss_gamma": 2,
    "verbose": True,
    "dropout": 0.0,
    # "checkpoint_path": None,
    # "overwrite_final_layer_dim": None,
    "use_augmentation": False,
}

# LSTM parameters
lstm_par = {
    "num_classes": NUM_CLASSES,
    "nHiddenUnits": 15,
    "numLayers": 1,
    "dropout": 0.0,
    "bidirectional": False,
    "convolutional": False,
}

lstm_train_opt = {
    "valid_perc": 0.1,
    "init_learn_rate": 0.005,
    "learn_drop_factor": 0.1,
    "max_epochs": 150,
    "minibatch_size": 10,
    "valid_patience": 8,
    "reduce_lr_patience": 10,
    "valid_frequency": 1.0,
    "gradient_threshold": 6,  # None to disable
    "focal_loss": True,
    "focal_loss_alpha": 0.25,
    "focal_loss_gamma": 2,
    "verbose": True,
}

# CLSTM parameters
clstm_par = {
    "num_classes": NUM_CLASSES,
    "nHiddenUnits": 15,
    "numFilters": 5,
    "numLayers": 1,
    "dropout": 0.0,
    "bidirectional": False,
    "convolutional": True,
}

clstm_train_opt = {
    "valid_perc": 0.1,
    "init_learn_rate": 0.005,
    "learn_drop_factor": 0.1,
    "max_epochs": 150,
    "minibatch_size": 10,
    "valid_patience": 8,
    "reduce_lr_patience": 4,
    "valid_frequency": 1.0,
    "gradient_threshold": 6,
    "focal_loss": False,
    "focal_loss_alpha": 0.25,
    "focal_loss_gamma": 2,
    "verbose": False,
}

# SVM parameters
svm_par = {"n_stat_mom": 4}

svm_train_opt = {
    "kernel_function": "poly",
    "poly_degree": 4,
    "kernel_scale": "auto",
    "box_constraint": 100,
    "standardize": True,
    "coding": "onevsone",
}

# Model settings
# BASE_MODELS = ["SVM", "CNN", "LSTM", "CLSTM"]
train = list(map(list, itertools.zip_longest(*train, fillvalue=None)))

print(f"Training on CONCAT...")
for mw in MOVING_WINDOWS:
    print(f"Training models for a sampling window of {mw} seconds")
    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")

    aug_train, aug_test = preprocessing.augment_data_ablation(
        train,
        test,
        summary,
        moving_window=mw,
        stride=STRIDE,
        homogeneous=HOMOGENEOUS_AUGMENTATION,
    )
    results = {}
    for j in range(5)[::-1]:
        model = "CNN"
        result_path = results_dir / f"results_split4_{j}_{model}_mw_{mw}.npy"
        print(f"Training {model} model with {mw} seconds...")
        print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        if result_path.exists():
            print(f"Results for {model} with {mw} seconds already exist. Skipping...")
            print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            continue
        (
            train_mcs_folds,
            test_mcs_folds,
        ) = preprocessing.apply_multichannel_spectogram(
            aug_train[j],
            aug_test,
            summary,
            mw,
            cnn_par["time_window"],
            cnn_par["time_overlap"],
            hamming=cnn_train_opt["hamming"],
        )
        results_per_fold = []
        maxs = np.stack(
            [
                ein.rearrange(train_mcs_folds[idx]["data"], "a b c d -> (a b c) d").max(
                    axis=0
                )
                for idx in range(N_FOLDS)
            ]
        ).max(axis=0)
        mins = np.stack(
            [
                ein.rearrange(train_mcs_folds[idx]["data"], "a b c d -> (a b c) d").min(
                    axis=0
                )
                for idx in range(N_FOLDS)
            ]
        ).min(axis=0)
        # Here
        for k in range(N_FOLDS):
            train_mcs, test_mcs = train_mcs_folds[k], test_mcs_folds[k]
            out = models.convolutional_neural_network(
                train_mcs,
                test_mcs,
                cnn_par,
                cnn_train_opt,
                dict(mw=mw, fold=k + 1, dataset=DATASET, mins=mins, maxs=maxs),
                random_state=RANDOM_STATE,
            )
            results_per_fold.append(out)

        results["pred"] = np.hstack([r["pred"] for r in results_per_fold])
        results["true"] = np.hstack([r["true"] for r in results_per_fold])
        results["conf"] = np.vstack([r["conf"] for r in results_per_fold])
        results["ftime"] = np.hstack([r["ftime"] for r in results_per_fold])
        results["ptime"] = np.hstack([r["ptime"] for r in results_per_fold])
        results["repr"] = np.vstack([r["repr"] for r in results_per_fold])

        results["channels"] = columns

        # Store terrain labels
        terrains = sorted(np.unique(terr_dfs["imu"].terrain))
        results["terrains"] = terrains

        np.save(result_path, results)
