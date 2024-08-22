# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models.hitransformer.ipynb.

# %% auto 0
__all__ = ['TriangularCausalMask', 'FullAttention', 'DataEmbedding_inverted', 'HiTransformer']

# %% ../../nbs/models.hitransformer.ipynb 6
import torch
import torch.nn as nn
import torch.nn.functional as F

import numpy as np

from math import sqrt

from ..losses.pytorch import MAE
from ..common._base_multivariate import BaseMultivariate

from neuralforecast.common._modules import (
    TransEncoder,
    TransEncoderLayer,
    AttentionLayer,
)

# %% ../../nbs/models.hitransformer.ipynb 9
class TriangularCausalMask:
    """
    TriangularCausalMask
    """

    def __init__(self, B, L, device="cpu"):
        mask_shape = [B, 1, L, L]
        with torch.no_grad():
            self._mask = torch.triu(
                torch.ones(mask_shape, dtype=torch.bool), diagonal=1
            ).to(device)

    @property
    def mask(self):
        return self._mask


class FullAttention(nn.Module):
    """
    FullAttention
    """

    def __init__(
        self,
        mask_flag=True,
        factor=5,
        scale=None,
        attention_dropout=0.1,
        output_attention=False,
    ):
        super(FullAttention, self).__init__()
        self.scale = scale
        self.mask_flag = mask_flag
        self.output_attention = output_attention
        self.dropout = nn.Dropout(attention_dropout)

    def forward(self, queries, keys, values, attn_mask, tau=None, delta=None):
        B, L, H, E = queries.shape
        _, S, _, D = values.shape
        scale = self.scale or 1.0 / sqrt(E)

        scores = torch.einsum("blhe,bshe->bhls", queries, keys)

        if self.mask_flag:
            if attn_mask is None:
                attn_mask = TriangularCausalMask(B, L, device=queries.device)

            scores.masked_fill_(attn_mask.mask, -np.inf)

        A = self.dropout(torch.softmax(scale * scores, dim=-1))
        V = torch.einsum("bhls,bshd->blhd", A, values)

        if self.output_attention:
            return (V.contiguous(), A)
        else:
            return (V.contiguous(), None)

# %% ../../nbs/models.hitransformer.ipynb 11
class DataEmbedding_inverted(nn.Module):
    """
    DataEmbedding_inverted
    """

    def __init__(self, c_in, hidden_size, dropout=0.1):
        super(DataEmbedding_inverted, self).__init__()
        self.value_embedding = nn.Linear(c_in, hidden_size)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x, x_mark):
        x = x.permute(0, 2, 1)
        # x: [Batch Variate Time]
        if x_mark is None:
            x = self.value_embedding(x)
        else:
            # the potential to take covariates (e.g. timestamps) as tokens
            x = self.value_embedding(torch.cat([x, x_mark.permute(0, 2, 1)], 1))
        # x: [Batch Variate hidden_size]
        return self.dropout(x)

# %% ../../nbs/models.hitransformer.ipynb 13
class HiTransformer(BaseMultivariate):
    """HiTransformer

    **Parameters:**<br>
    `h`: int, Forecast horizon. <br>
    `input_size`: int, autorregresive inputs size, y=[1,2,3,4] input_size=2 -> y_[t-2:t]=[1,2].<br>
    `n_series`: int, number of time-series.<br>
    `futr_exog_list`: str list, future exogenous columns.<br>
    `hist_exog_list`: str list, historic exogenous columns.<br>
    `stat_exog_list`: str list, static exogenous columns.<br>
    `hidden_size`: int, dimension of the model.<br>
    `n_heads`: int, number of heads.<br>
    `e_layers`: int, number of encoder layers.<br>
    `d_layers`: int, number of decoder layers.<br>
    `d_ff`: int, dimension of fully-connected layer.<br>
    `factor`: int, attention factor.<br>
    `dropout`: float, dropout rate.<br>
    `use_norm`: bool, whether to normalize or not.<br>
    `loss`: PyTorch module, instantiated train loss class from [losses collection](https://nixtla.github.io/neuralforecast/losses.pytorch.html).<br>
    `valid_loss`: PyTorch module=`loss`, instantiated valid loss class from [losses collection](https://nixtla.github.io/neuralforecast/losses.pytorch.html).<br>
    `max_steps`: int=1000, maximum number of training steps.<br>
    `learning_rate`: float=1e-3, Learning rate between (0, 1).<br>
    `num_lr_decays`: int=-1, Number of learning rate decays, evenly distributed across max_steps.<br>
    `early_stop_patience_steps`: int=-1, Number of validation iterations before early stopping.<br>
    `val_check_steps`: int=100, Number of training steps between every validation loss check.<br>
    `batch_size`: int=32, number of different series in each batch.<br>
    `step_size`: int=1, step size between each window of temporal data.<br>
    `scaler_type`: str='identity', type of scaler for temporal inputs normalization see [temporal scalers](https://nixtla.github.io/neuralforecast/common.scalers.html).<br>
    `random_seed`: int=1, random_seed for pytorch initializer and numpy generators.<br>
    `num_workers_loader`: int=os.cpu_count(), workers to be used by `TimeSeriesDataLoader`.<br>
    `drop_last_loader`: bool=False, if True `TimeSeriesDataLoader` drops last non-full batch.<br>
    `alias`: str, optional,  Custom name of the model.<br>
    `optimizer`: Subclass of 'torch.optim.Optimizer', optional, user specified optimizer instead of the default choice (Adam).<br>
    `optimizer_kwargs`: dict, optional, list of parameters used by the user specified `optimizer`.<br>
    `lr_scheduler`: Subclass of 'torch.optim.lr_scheduler.LRScheduler', optional, user specified lr_scheduler instead of the default choice (StepLR).<br>
    `lr_scheduler_kwargs`: dict, optional, list of parameters used by the user specified `lr_scheduler`.<br>
    `**trainer_kwargs`: int,  keyword trainer arguments inherited from [PyTorch Lighning's trainer](https://pytorch-lightning.readthedocs.io/en/stable/api/pytorch_lightning.trainer.trainer.Trainer.html?highlight=trainer).<br>

    **References**<br>
    - [Yong Liu, Tengge Hu, Haoran Zhang, Haixu Wu, Shiyu Wang, Lintao Ma, Mingsheng Long. "HiTransformer: Inverted Transformers Are Effective for Time Series Forecasting"](https://arxiv.org/abs/2310.06625)
    """

    # Class attributes
    SAMPLING_TYPE = "multivariate"
    EXOGENOUS_FUTR = False
    EXOGENOUS_HIST = False
    EXOGENOUS_STAT = False

    def __init__(
        self,
        h,
        input_size,
        n_series,
        futr_exog_list=None,
        hist_exog_list=None,
        stat_exog_list=None,
        hidden_size: int = 512,
        n_heads: int = 8,
        e_layers: int = 2,
        d_layers: int = 1,
        d_ff: int = 2048,
        factor: int = 1,
        dropout: float = 0.1,
        use_norm: bool = True,
        loss=MAE(),
        valid_loss=None,
        max_steps: int = 1000,
        learning_rate: float = 1e-3,
        num_lr_decays: int = -1,
        early_stop_patience_steps: int = -1,
        val_check_steps: int = 100,
        batch_size: int = 32,
        step_size: int = 1,
        scaler_type: str = "identity",
        random_seed: int = 1,
        num_workers_loader: int = 0,
        drop_last_loader: bool = False,
        optimizer=None,
        optimizer_kwargs=None,
        lr_scheduler=None,
        lr_scheduler_kwargs=None,
        **trainer_kwargs
    ):

        super(HiTransformer, self).__init__(
            h=h,
            input_size=input_size,
            n_series=n_series,
            stat_exog_list=None,
            futr_exog_list=None,
            hist_exog_list=None,
            loss=loss,
            valid_loss=valid_loss,
            max_steps=max_steps,
            learning_rate=learning_rate,
            num_lr_decays=num_lr_decays,
            early_stop_patience_steps=early_stop_patience_steps,
            val_check_steps=val_check_steps,
            batch_size=batch_size,
            step_size=step_size,
            scaler_type=scaler_type,
            random_seed=random_seed,
            num_workers_loader=num_workers_loader,
            drop_last_loader=drop_last_loader,
            optimizer=optimizer,
            optimizer_kwargs=optimizer_kwargs,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
            **trainer_kwargs
        )

        self.enc_in = n_series
        self.dec_in = n_series
        self.c_out = n_series
        self.hidden_size = hidden_size
        self.n_heads = n_heads
        self.e_layers = e_layers
        self.d_layers = d_layers
        self.d_ff = d_ff
        self.factor = factor
        self.dropout = dropout
        self.use_norm = use_norm

        # Architecture
        self.enc_embedding = DataEmbedding_inverted(
            input_size, self.hidden_size, self.dropout
        )

        # Zamena TransEncoder sa nn.Linear
        self.encoder = nn.Linear(self.hidden_size, self.hidden_size)

        self.projectors_num = 3

        self.projector = nn.Linear(self.hidden_size, h, bias=True)

        # Define a list of projectors, one for each segment
        self.projectors = nn.ModuleList([nn.Linear(self.hidden_size, h, bias=True) for _ in range(self.projectors_num)])

        # Final Linear layer
        self.final = nn.Linear(h * self.projectors_num, h, bias=True)

        # Define additional projectors after final
        self.additional_projectors = nn.ModuleList(
            [nn.Linear(h, h // self.projectors_num, bias=True) for _ in range(self.projectors_num)])

    def ewma(self, data, alpha):
        result = torch.zeros_like(data)
        result[:, 0, :] = data[:, 0, :]
        for t in range(1, data.size(1)):
            result[:, t, :] = alpha * data[:, t, :] + (1 - alpha) * result[:, t - 1, :]
        return result

    def multi_ewma(self, data, base_alpha, iterations):
        for i in range(iterations):
            alpha = base_alpha * (i + 1)
            data = self.gaussian_filter(data, 3, base_alpha)
        return data

    # Funkcija za primjenu Gaussovog filtera
    def gaussian_filter44(self, data, kernel_size = 3, sigma = 1):
        kernel = torch.arange(kernel_size).float() - (kernel_size - 1) / 2
        kernel = torch.exp(-0.5 * (kernel / sigma).pow(2))
        kernel = kernel / kernel.sum()  # Normalizacija
        kernel = kernel.view(1, 1, -1).to(data.device)
        smoothed_data = F.conv1d(data.unsqueeze(0).unsqueeze(0), kernel, padding=kernel_size // 2).squeeze(0).squeeze(0)
        return smoothed_data

    def gaussian_filter(self, data, kernel_size=3, sigma=0.2):
        # Create a 1D Gaussian kernel
        kernel = torch.arange(kernel_size, device=data.device) - (kernel_size - 1) / 2
        kernel = torch.exp(-0.5 * (kernel / sigma) ** 2)
        kernel = kernel / kernel.sum()  # Normalize kernel

        # Reshape kernel for 1D convolution
        kernel = kernel.view(1, 1, -1)

        # Apply the Gaussian filter along the time dimension (dim=1)
        result = torch.zeros_like(data)
        for i in range(data.size(0)):  # Iterate over the batch
            for j in range(data.size(2)):  # Iterate over the feature dimension
                # Ensure data and kernel are on the same device
                result[i, :, j] = F.conv1d(data[i, :, j].unsqueeze(0).unsqueeze(0),
                                           kernel, padding=kernel_size // 2).squeeze(0).squeeze(0)
        return result


    def forecast(self, x_enc):
        if self.use_norm:
            means = x_enc.mean(1, keepdim=True).detach()
            x_enc = x_enc - means
            stdev = torch.sqrt(
                torch.var(x_enc, dim=1, keepdim=True, unbiased=False) + 1e-5
            )
            x_enc /= stdev

            smooth_left_copy = self.multi_ewma(x_enc, base_alpha=0.1, iterations=5)
            smooth_right_copy = self.multi_ewma(x_enc.flip(1), base_alpha=0.1, iterations=5).flip(1)

            x_enc = (smooth_left_copy + smooth_right_copy) / 2

        _, _, N = x_enc.shape

        # Embedding
        enc_out = self.enc_embedding(x_enc, None)

        # Zamenjeni enkoder
        enc_out = self.encoder(enc_out)

        # Generate predictions from each segment using corresponding projectors
        dec_outs = []
        for i, projector in enumerate(self.projectors):
            dec_outs.append(projector(enc_out))

        # Concatenate the outputs from all projectors
        dec_out = torch.cat(dec_outs, dim=2)

        # Pass through the final linear layer
        dec_out = self.final(dec_out)

        # Additional projectors after final
        final_outs = []
        for projector in self.additional_projectors:
            final_outs.append(projector(dec_out).permute(0, 2, 1))

        dec_out = torch.cat(final_outs, dim=1)

        if self.use_norm:
            dec_out = dec_out * (stdev[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))
            dec_out = dec_out + (means[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))

        return dec_out

    def forward(self, windows_batch):
        insample_y = windows_batch["insample_y"]

        y_pred = self.forecast(insample_y)
        y_pred = y_pred[:, -self.h :, :]
        y_pred = self.loss.domain_map(y_pred)

        # domain_map might have squeezed the last dimension in case n_series == 1
        if y_pred.ndim == 2:
            return y_pred.unsqueeze(-1)
        else:
            return y_pred
