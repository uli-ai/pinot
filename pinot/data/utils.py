# =============================================================================
# IMPORTS
# =============================================================================
import pinot
import pandas as pd
import numpy as np
import torch
import dgl
import random

# =============================================================================
# MODULE FUNCTIONS
# =============================================================================


def from_csv(
    path,
    toolkit="rdkit",
    smiles_col=-1,
    y_cols=[-2],
    seed=2666,
    scale=1.0,
    dropna=False,
    **kwargs
):
    """ Read csv from file.
    """

    def _from_csv():
        df = pd.read_csv(path, error_bad_lines=False, **kwargs)

        if dropna is True:
            df = df.dropna(axis=0, subset=[df.columns[y_cols[0]]])

        df_smiles = df.iloc[:, smiles_col]
        df_y = df.iloc[:, y_cols]

        if toolkit == "rdkit":
            from rdkit import Chem

            df_smiles = [str(x) for x in df_smiles]

            idxs = [
                idx
                for idx in range(len(df_smiles))
                if "nan" not in df_smiles[idx]
            ]

            df_smiles = [df_smiles[idx] for idx in idxs]

            mols = [Chem.MolFromSmiles(smiles) for smiles in df_smiles]
            gs = [pinot.graph.from_rdkit_mol(mol) for mol in mols]

        elif toolkit == "openeye":
            from openeye import oechem

            mols = [
                oechem.OESmilesToMol(oechem.OEGraphMol(), smiles)
                for smiles in df_smiles
            ]
            gs = [pinot.graph.from_oemol(mol) for mol in mols]

        ds = list(
            zip(
                gs,
                list(
                    torch.tensor(
                        scale * df_y.values[idxs], dtype=torch.float32
                    )
                ),
            )
        )
        random.seed(seed)
        random.shuffle(ds)

        return ds

    return _from_csv


def load_unlabeled_data(path, size=0.1, toolkit="rdkit", seed=2666):
    """ Read from unlabeled data set as background data
    """

    def _from_txt():
        f = open(path, "r")
        df_smiles = [line.rstrip() for line in f]
        # Since loading the whole data set takes a lot of time
        # Load only a subset of the data instead
        num_mols = int(len(df_smiles) * size)
        df_smiles = df_smiles[:num_mols]
        # Create "fake" labels
        df_y = torch.FloatTensor([1 for _ in range(num_mols)])

        if toolkit == "rdkit":
            from rdkit import Chem

            mols = [Chem.MolFromSmiles(smiles) for smiles in df_smiles]
            gs = [pinot.graph.from_rdkit_mol(mol) for mol in mols]

        elif toolkit == "openeye":
            from openeye import oechem

            mols = [
                oechem.OESmilesToMol(oechem.OEGraphMol(), smiles)
                for smiles in df_smiles
            ]
            gs = [pinot.graph.from_oemol(mol) for mol in mols]

        gs = list(zip(gs, df_y))
        random.seed(seed)
        random.shuffle(gs)

        return gs

    return _from_txt


def normalize(ds):
    """ Get mean and std.
    """

    gs, ys = tuple(zip(*ds))
    y_mean = np.mean(ys)
    y_std = np.std(ys)

    def norm(y):
        return (y - y_mean) / y_std

    def unnorm(y):
        return y * y_std + y_mean

    return y_mean, y_std, norm, unnorm


def split(ds, partition):
    """ Split the dataset according to some partition.
    """
    n_data = len(ds)

    # get the actual size of partition
    partition = [int(n_data * x / sum(partition)) for x in partition]

    ds_batched = []
    idx = 0
    for p_size in partition:
        ds_batched.append(ds[idx : idx + p_size])
        idx += p_size

    return ds_batched


def batch(ds, batch_size, seed=2666):
    """ Batch graphs and values after shuffling.
    """
    # get the numebr of data
    n_data_points = len(ds)
    n_batches = n_data_points // batch_size  # drop the rest

    random.seed(seed)
    random.shuffle(ds)
    gs, ys = tuple(zip(*ds))

    gs_batched = [
        dgl.batch(gs[idx * batch_size : (idx + 1) * batch_size])
        for idx in range(n_batches)
    ]

    ys_batched = [
        torch.stack(ys[idx * batch_size : (idx + 1) * batch_size], dim=0)
        for idx in range(n_batches)
    ]

    return list(zip(gs_batched, ys_batched))
