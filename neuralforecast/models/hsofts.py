# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models.softs.ipynb.

# %% auto 0
__all__ = ['DataEmbedding_inverted', 'STAD', 'HSOFTS']

# %% ../../nbs/models.softs.ipynb 4
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..losses.pytorch import MAE
from ..common._base_multivariate import BaseMultivariate
from ..common._modules import TransEncoder, TransEncoderLayer

from ..layers.kan import KAN, KANLinear

# %% ../../nbs/models.softs.ipynb 6
class DataEmbedding_inverted(nn.Module):
    """
    Data Embedding
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DataEmbedding_inverted, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x, x_mark):
        x = x.permute(0, 2, 1)
        # x: [Batch Variate Time]
        if x_mark is None:
            x = self.value_embedding(x)
        else:
            # the potential to take covariates (e.g. timestamps) as tokens
            x = self.value_embedding(torch.cat([x, x_mark.permute(0, 2, 1)], 1))
        # x: [Batch Variate d_model]
        return self.dropout(x)

# %% ../../nbs/models.softs.ipynb 8
class STAD(nn.Module):

    def __init__(self, d_series, d_core, dropout_rate=0.5, max_len=5000):
        super(STAD, self).__init__()
        """
        Adaptive STAR with Temporal Embeddings and Dropout
        """

        self.temporal_embedding = TemporalEmbedding(d_series, max_len)
        self.gen1 = nn.Linear(d_series, d_series)
        self.gen2 = nn.Linear(d_series, d_core)

        # Adaptive Core Formation
        self.adaptive_core = nn.Linear(d_series, d_core)

        self.gen3 = nn.Linear(d_series + d_core, d_series)
        self.gen4 = nn.Linear(d_series, d_series)

        # Dropout layers
        self.dropout1 = nn.Dropout(dropout_rate)
        self.dropout2 = nn.Dropout(dropout_rate)
        self.dropout3 = nn.Dropout(dropout_rate)

    def forward(self, input, *args, **kwargs):
        batch_size, channels, d_series = input.shape

        # Apply temporal embedding
        input = self.temporal_embedding(input)

        # Set FFN
        combined_mean = F.gelu(self.gen1(input))
        combined_mean = self.dropout1(combined_mean)  # Apply dropout
        combined_mean = self.gen2(combined_mean)

        # Adaptive Core Formation
        adaptive_core = self.adaptive_core(input.mean(dim=1, keepdim=True))
        combined_mean = combined_mean + adaptive_core

        # Stochastic pooling
        if self.training:
            ratio = F.softmax(combined_mean, dim=1)
            ratio = ratio.permute(0, 2, 1)
            ratio = ratio.reshape(-1, channels)
            indices = torch.multinomial(ratio, 1)
            indices = indices.view(batch_size, -1, 1).permute(0, 2, 1)
            combined_mean = torch.gather(combined_mean, 1, indices)
            combined_mean = combined_mean.repeat(1, channels, 1)
        else:
            weight = F.softmax(combined_mean, dim=1)
            combined_mean = torch.sum(combined_mean * weight, dim=1, keepdim=True).repeat(1, channels, 1)

        combined_mean = self.dropout2(combined_mean)  # Apply dropout

        # MLP fusion
        combined_mean_cat = torch.cat([input, combined_mean], -1)
        combined_mean_cat = F.gelu(self.gen3(combined_mean_cat))
        combined_mean_cat = self.dropout3(combined_mean_cat)  # Apply dropout
        combined_mean_cat = self.gen4(combined_mean_cat)
        output = combined_mean_cat

        return output, None



class TemporalEmbedding(nn.Module):
    def __init__(self, d_series, max_len=5000):
        super(TemporalEmbedding, self).__init__()
        self.position_embedding = nn.Parameter(torch.zeros(1, max_len, d_series), requires_grad=False)
        position = torch.arange(0, max_len).unsqueeze(1).float()
        div_term = torch.exp(torch.arange(0, d_series, 2).float() * -(torch.log(torch.tensor(10000.0)) / d_series))
        self.position_embedding[:, :, 0::2] = torch.sin(position * div_term)
        self.position_embedding[:, :, 1::2] = torch.cos(position * div_term)

    def forward(self, x):
        x = x + self.position_embedding[:, :x.size(1)]
        return x


import torch
import torch.nn as nn
import torch
import torch.nn as nn

import torch
import torch.nn as nn

import torch
import torch.nn as nn
import torch
import torch.nn as nn
import math

import torch
import torch.nn as nn

import torch
import torch.nn as nn

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

        # Apply the linear embedding to the EWMA-smoothed data
        x_ewma_emb = self.value_embedding(ewma)

        return self.dropout(x_ewma_emb)

class EWMAEmbedding2(nn.Module):
    """
    EWMA Embedding for smoothing the time series data.
    """

    def __init__(self, c_in, d_model, alpha=0.3, dropout=0.1):
        super(EWMAEmbedding, self).__init__()
        self.alpha = alpha  # Smoothing factor for EWMA
        self.value_embedding = nn.Linear(c_in, d_model)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x, x_mark=None):
        # x: [Batch, Variate, Time]
        x = x.permute(0, 2, 1)  # Transpose to [Batch, Time, Variate]

        # Calculate EWMA for each variate in the series
        ewma = torch.zeros_like(x)
        ewma[:, 0, :] = x[:, 0, :]  # Set the first value as it is
        for t in range(1, x.size(1)):
            ewma[:, t, :] = self.alpha * x[:, t, :] + (1 - self.alpha) * ewma[:, t - 1, :]

        # Apply the linear embedding to the EWMA-smoothed data
        x_ewma_emb = self.value_embedding(ewma)

        return self.dropout(x_ewma_emb)


class DiffEmbeddingx(nn.Module):
    """
    Diff Embedding with sinus and cosinus transformation for diff(1).
    """

    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.d_model = d_model
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

        # Apply sinus and cosinus transformation
        position = torch.arange(0, x_diff.size(1), device=x.device).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, self.d_model, 2, device=x.device) * -(math.log(10000.0) / self.d_model))

        sinusoidal_embedding = torch.zeros(x_diff.size(0), x_diff.size(1), self.d_model, device=x.device)
        sinusoidal_embedding[:, :, 0::2] = torch.sin(position * div_term)
        sinusoidal_embedding[:, :, 1::2] = torch.cos(position * div_term)

        # Apply the linear embedding to the diff values and combine with sinusoidal embedding
        x_diff_emb = self.value_embedding(x_diff) + sinusoidal_embedding

        return self.dropout(x_diff_emb)


class DiffEmbedding(nn.Module):
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

class DiffEmbedding2(nn.Module):
    def __init__(self, c_in, d_model, dropout=0.1):
        super(DiffEmbedding, self).__init__()
        self.value_embedding = nn.Linear(c_in, d_model)
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, x):
        # Calculate diff(1) - differences of first order along the time dimension
        x_diff = x[:, :, 1:] - x[:, :, :-1]

        # Embedding for the differences
        x_diff = self.value_embedding(x_diff)

        # Apply dropout
        x_diff = self.dropout(x_diff)

        return x_diff


# %% ../../nbs/models.hsofts.ipynb 10
class HSOFTS(BaseMultivariate):
    """SOFTS

    **Parameters:**<br>
    `h`: int, Forecast horizon. <br>
    `input_size`: int, autorregresive inputs size, y=[1,2,3,4] input_size=2 -> y_[t-2:t]=[1,2].<br>
    `n_series`: int, number of time-series.<br>
    `futr_exog_list`: str list, future exogenous columns.<br>
    `hist_exog_list`: str list, historic exogenous columns.<br>
    `stat_exog_list`: str list, static exogenous columns.<br>
    `hidden_size`: int, dimension of the model.<br>
    `d_core`: int, dimension of core in STAD.<br>
    `e_layers`: int, number of encoder layers.<br>
    `d_ff`: int, dimension of fully-connected layer.<br>
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
    [Lu Han, Xu-Yang Chen, Han-Jia Ye, De-Chuan Zhan. "SOFTS: Efficient Multivariate Time Series Forecasting with Series-Core Fusion"](https://arxiv.org/pdf/2404.14197)
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
        d_core: int = 512,
        e_layers: int = 2,
        d_ff: int = 2048,
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

        super(HSOFTS, self).__init__(
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
        self.h = h
        self.enc_in = n_series
        self.dec_in = n_series
        self.c_out = n_series
        self.use_norm = use_norm

        # Architecture: Tri embedding sloja
        self.value_embedding = DataEmbedding_inverted(input_size, hidden_size, dropout)
        self.diff_embedding = DiffEmbedding(input_size, hidden_size, dropout)
        #self.ewma_embedding = EWMAEmbedding(input_size, hidden_size, dropout=dropout)

        self.encoder = TransEncoder(
            [
                TransEncoderLayer(
                    STAD(hidden_size, d_core),
                    hidden_size,
                    d_ff,
                    dropout=dropout,
                    activation=F.gelu,
                )
                for l in range(e_layers)
            ]
        )

        self.projection = nn.Linear(hidden_size, self.h, bias=True)

    def forecast(self, x_enc):
        # Normalization from Non-stationary Transformer
        if self.use_norm:
            means = x_enc.mean(1, keepdim=True).detach()
            x_enc = x_enc - means
            stdev = torch.sqrt(
                torch.var(x_enc, dim=1, keepdim=True, unbiased=False) + 1e-5
            )
            x_enc /= stdev

        _, _, N = x_enc.shape

        # Generisanje embeddinga za originalne vrednosti, razlike, i EWMA
        value_emb = self.value_embedding(x_enc, None)
        #diff_emb = self.diff_embedding(x_enc)
        ewma_emb = self.ewma_embedding(x_enc)

        # Kombinacija svih embeddinga (npr. sabiranje)+ diff_emb #
        combined_emb = value_emb + ewma_emb  # Možete koristiti torch.cat za konkatenaciju

        enc_out, attns = self.encoder(combined_emb, attn_mask=None)
        dec_out = self.projection(enc_out).permute(0, 2, 1)[:, :, :N]

        # De-Normalization from Non-stationary Transformer
        if self.use_norm:
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