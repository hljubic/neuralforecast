# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models.HiTransformer.ipynb.

# %% auto 0
__all__ = ['TriangularCausalMask', 'FullAttention', 'DataEmbedding_inverted', 'HiTransformer']

# %% ../../nbs/models.HiTransformer.ipynb 6
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

# %% ../../nbs/models.HiTransformer.ipynb 9
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

class DiffEmbedding(nn.Module):
    """
    Embedding without EWMA and activation applied on the value embeddings.
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)  # Value embedding sloj
        self.linear_layer = nn.Linear(d_model, d_model)  # Linear sloj
        self.batch_norm = nn.BatchNorm1d(d_model)  # Batch Normalization sloj

        # Simple Attention mechanism
        self.attention = nn.MultiheadAttention(embed_dim=d_model, num_heads=1, dropout=dropout)

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        if x_mark is not None:
            # The potential to take covariates (e.g. timestamps) as tokens
            x_mark = x_mark.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]
            x = torch.cat([x, x_mark], dim=2)  # Concatenate along the feature dimension

        # Apply the value embedding
        x_emb = self.value_embedding(x)

        # Apply the Linear layer
        x = self.linear_layer(x_emb)

        # Apply Batch Normalization
        x = self.batch_norm(x.permute(0, 2, 1)).permute(0, 2, 1)

        # Apply Attention
        x = x.permute(1, 0, 2)  # Transpose for attention: [Time, Batch, d_model]
        x, _ = self.attention(x, x, x)
        x = x.permute(1, 0, 2)  # Transpose back to [Batch, Time, d_model]

        # Residual connection
        x = x + x_emb

        return x


class DiffEmbedding1234(nn.Module):
    """
    Diff Embedding with added initial zero value to maintain dimensions.
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)  # Value embedding sloj
        self.linear_layer = nn.Linear(d_model, d_model)  # Linear sloj
        self.activation = nn.Tanh()  # tanh aktivacijska funkcija
        self.alpha = 0.1  # Parametar za EWMA

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate first order differences along the time dimension
        x_diff = x[:, 1:, :] - x[:, :-1, :]

        # Add an initial zero to keep the dimension consistent
        initial_zero = torch.zeros(x.size(0), 1, x.size(2), device=x.device)  # [Batch, 1, Variate]
        x_diff = torch.cat([initial_zero, x_diff], dim=1)  # [Batch, Time, Variate]

        if x_mark is not None:
            # The potential to take covariates (e.g. timestamps) as tokens
            x_mark = x_mark.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]
            x_diff = torch.cat([x_diff, x_mark], dim=2)  # Concatenate along the feature dimension

        # Apply the value embedding
        x_emb = self.value_embedding(x_diff)

        # Apply EWMA smoothing from left to right
        x_ewma_lr = self.ewma(x_emb, self.alpha)

        # Apply EWMA smoothing from right to left
        x_ewma_rl = self.ewma(x_emb.flip(dims=[1]), self.alpha).flip(dims=[1])

        # Calculate the arithmetic mean of the two smoothed sequences
        x_smooth = (x_ewma_lr + x_ewma_rl) / 2.0

        # Apply the Linear layer followed by Tanh activation
        x = self.linear_layer(x_smooth)

        return x

    def ewma(self, x, alpha):
        """
        Computes the Exponential Weighted Moving Average (EWMA) of a sequence.
        x: [Batch, Time, Variate]
        alpha: smoothing factor
        """
        x_ewma = torch.zeros_like(x)
        x_ewma[:, 0, :] = x[:, 0, :]  # Initialize with the first value

        for t in range(1, x.size(1)):
            x_ewma[:, t, :] = alpha * x[:, t, :] + (1 - alpha) * x_ewma[:, t-1, :]

        return x_ewma

class DiffEmbedding444(nn.Module):
    """
    Diff Embedding with added initial zero value to maintain dimensions.
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.linear_layer = nn.Linear(c_in, d_model)  # Linear sloj
        self.activation = nn.Tanh()  # tanh aktivacijska funkcija

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate first order differences along the time dimension
        x_diff = x[:, 1:, :] - x[:, :-1, :]

        # Add an initial zero to keep the dimension consistent
        initial_zero = torch.zeros(x.size(0), 1, x.size(2), device=x.device)  # [Batch, 1, Variate]
        x_diff = torch.cat([initial_zero, x_diff], dim=1)  # [Batch, Time, Variate]

        if x_mark is not None:
            # The potential to take covariates (e.g. timestamps) as tokens
            x_mark = x_mark.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]
            x_diff = torch.cat([x_diff, x_mark], dim=2)  # Concatenate along the feature dimension

        # Apply the Linear layer followed by Tanh activation
        x = self.activation(self.linear_layer(x_diff))

        # x: [Batch, Time, d_model]
        return x

class DiffEmbedding44(nn.Module):
    """
    Diff Embedding with added initial zero value to maintain dimensions.
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)
        self.linear_layer = nn.Linear(d_model, d_model)  # Linear sloj
        self.activation = nn.Tanh()  # tanh aktivacijska funkcija

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate first order differences along the time dimension
        x_diff = x[:, 1:, :] - x[:, :-1, :]

        # Add an initial zero to keep the dimension consistent
        initial_zero = torch.zeros(x.size(0), 1, x.size(2), device=x.device)  # [Batch, 1, Variate]
        x_diff = torch.cat([initial_zero, x_diff], dim=1)  # [Batch, Time, Variate]

        if x_mark is None:
            x = self.value_embedding(x_diff)
        else:
            # The potential to take covariates (e.g. timestamps) as tokens
            x_mark = x_mark.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]
            x = self.value_embedding(torch.cat([x_diff, x_mark], dim=2))  # Concatenate along the feature dimension

        # Apply the additional Linear layer followed by Tanh activation
        x = self.activation(self.linear_layer(x))

        # x: [Batch, Time, d_model]
        return x

class DiffEmbedding24(nn.Module):
    """
    Diff Embedding with added initial zero value to maintain dimensions.
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate first order differences along the time dimension
        x_diff = x[:, 1:, :] - x[:, :-1, :]

        # Add an initial zero to keep the dimension consistent
        initial_zero = torch.zeros(x.size(0), 1, x.size(2), device=x.device)  # [Batch, 1, Variate]
        x_diff = torch.cat([initial_zero, x_diff], dim=1)  # [Batch, Time, Variate]

        if x_mark is None:
            x = self.value_embedding(x_diff)
        else:
            # The potential to take covariates (e.g. timestamps) as tokens
            x_mark = x_mark.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]
            x = self.value_embedding(torch.cat([x_diff, x_mark], dim=2))  # Concatenate along the feature dimension

        # x: [Batch, Time, d_model]
        return self.dropout(x)


class EWMAEmbedding(nn.Module):
    """
    EWMA Embedding with forward and backward smoothing, followed by averaging.
    """

    def __init__(self, c_in, d_model, alpha=0.1, dropout=0.1):
        super(EWMAEmbedding, self).__init__()
        self.alpha = alpha  # Smoothing factor for EWMA
        self.value_embedding = nn.Linear(c_in, d_model)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate EWMA from left to right (forward)
        ewma_forward = torch.zeros_like(x)
        ewma_forward[:, 0, :] = x[:, 0, :]  # Set the first value as it is
        for t in range(1, x.size(1)):
            ewma_forward[:, t, :] = self.alpha * x[:, t, :] + (1 - self.alpha) * ewma_forward[:, t - 1, :]

        # Calculate EWMA from right to left (backward)
        ewma_backward = torch.zeros_like(x)
        ewma_backward[:, -1, :] = x[:, -1, :]  # Set the last value as it is
        for t in range(x.size(1) - 2, -1, -1):
            ewma_backward[:, t, :] = self.alpha * x[:, t, :] + (1 - self.alpha) * ewma_backward[:, t + 1, :]

        # Average the forward and backward EWMA
        ewma = (ewma_forward + ewma_backward) / 2



# %% ../../nbs/models.HiTransformer.ipynb 11
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

# %% ../../nbs/models.HiTransformer.ipynb 13
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
        self.diff_embedding = DiffEmbedding(c_in=input_size, d_model=self.hidden_size, dropout=self.dropout)

        # Adjust the input size of the encoder if concatenating embeddings
        self.encoder = TransEncoder(
            [
                TransEncoderLayer(
                    AttentionLayer(
                        FullAttention(
                            False, self.factor, attention_dropout=self.dropout
                        ),
                        self.hidden_size * 1,  # Adjust for concatenated embeddings
                        self.n_heads,
                    ),
                    self.hidden_size * 1,  # Adjust for concatenated embeddings
                    self.d_ff,
                    dropout=self.dropout,
                    activation=F.gelu,
                )
                for l in range(self.e_layers)
            ],
            norm_layer=torch.nn.LayerNorm(self.hidden_size * 1),
        )

        # Adjust the projector layer to match the new hidden size
        self.projector = nn.Linear(self.hidden_size * 1, h, bias=True)

    def forecast(self, x_enc):
        if self.use_norm:
            # Normalization from Non-stationary Transformer
            means = x_enc.mean(1, keepdim=True).detach()
            x_enc = x_enc - means
            stdev = torch.sqrt(
                torch.var(x_enc, dim=1, keepdim=True, unbiased=False) + 1e-5
            )
            x_enc /= stdev

        _, _, N = x_enc.shape  # B L N

        # Embedding
        # DataEmbedding_inverted
        enc_out = self.enc_embedding(x_enc, None)

        # DiffEmbedding
        #enc_out_diff = self.diff_embedding(x_enc)

        # Concatenate the two embeddings along the feature dimension
        #enc_out = torch.cat([enc_out_data, enc_out_diff], dim=2)  # Concatenate along the feature dimension

        # Encode the concatenated embeddings
        enc_out, attns = self.encoder(enc_out, attn_mask=None)

        # Project to the desired output shape
        dec_out = self.projector(enc_out).permute(0, 2, 1)[:, :, :N]

        if self.use_norm:
            # De-Normalization from Non-stationary Transformer
            dec_out = dec_out * (stdev[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))
            dec_out = dec_out + (means[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))

        return dec_out

    def forward(self, windows_batch):
        insample_y = windows_batch["insample_y"]

        y_pred = self.forecast(insample_y)
        y_pred = y_pred[:, -self.h:, :]
        y_pred = self.loss.domain_map(y_pred)

        # domain_map might have squeezed the last dimension in case n_series == 1
        if y_pred.ndim == 2:
            return y_pred.unsqueeze(-1)
        else:
            return y_pred