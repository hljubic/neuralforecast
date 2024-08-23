# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models.hsofts.ipynb.

# %% auto 0
__all__ = ['DataEmbedding_inverted', 'STAD', 'HSOFTS']

# %% ../../nbs/models.hsofts.ipynb 4
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..losses.pytorch import MAE
from ..common._base_multivariate import BaseMultivariate
from ..common._modules import TransEncoder, TransEncoderLayer

# %% ../../nbs/models.hsofts.ipynb 6
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

# %% ../../nbs/models.hsofts.ipynb 8
class STAD(nn.Module):
    """
    STar Aggregate Dispatch Module
    """

    def __init__(self, d_series, d_core):
        super(STAD, self).__init__()

        self.gen1 = nn.Linear(d_series, d_series)
        self.gen2 = nn.Linear(d_series, d_core)
        self.gen3 = nn.Linear(d_series + d_core, d_series)
        self.gen4 = nn.Linear(d_series, d_series)

    def forward(self, input, *args, **kwargs):
        batch_size, channels, d_series = input.shape

        # set FFN
        combined_mean = F.gelu(self.gen1(input))
        combined_mean = self.gen2(combined_mean)

        # stochastic pooling
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
            combined_mean = torch.sum(
                combined_mean * weight, dim=1, keepdim=True
            ).repeat(1, channels, 1)

        # mlp fusion
        combined_mean_cat = torch.cat([input, combined_mean], -1)
        combined_mean_cat = F.gelu(self.gen3(combined_mean_cat))
        combined_mean_cat = self.gen4(combined_mean_cat)
        output = combined_mean_cat

        return output, None

# %% ../../nbs/models.hsofts.ipynb 10
class HSOFTS(BaseMultivariate):
    """HSOFTS

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
    [Lu Han, Xu-Yang Chen, Han-Jia Ye, De-Chuan Zhan. "HSOFTS: Efficient Multivariate Time Series Forecasting with Series-Core Fusion"](https://arxiv.org/pdf/2404.14197)
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

        self.hidden_size = hidden_size
        self.projectors_num = 4

        # Architecture
        self.enc_embedding = DataEmbedding_inverted(input_size, hidden_size, dropout)

        self.encoder2 = TransEncoder(
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
        self.encoder = nn.Linear(self.hidden_size, self.hidden_size)

        self.projection = nn.Linear(hidden_size, self.h, bias=True)


        # Define a list of projectors, one for each segment
        self.projectors = nn.ModuleList([nn.Linear(self.hidden_size, h, bias=True) for _ in range(self.projectors_num)])

        # Final Linear layer
        self.final = nn.Linear(h * self.projectors_num, h, bias=True)

        # Define additional projectors after final
        self.additional_projectors = nn.ModuleList(
            [nn.Linear(h, h // self.projectors_num, bias=True) for _ in range(self.projectors_num)])

    def forecast(self, x_enc):
        # Normalization from Non-stationary Transformer
        if self.use_norm:
            means = x_enc.mean(1, keepdim=True).detach()
            x_enc = x_enc - means
            stdev = torch.sqrt(
                torch.var(x_enc, dim=1, keepdim=True, unbiased=False) + 1e-5
            )
            x_enc /= stdev

            x_enc = self.normalize_frequencies(x_enc, 0.75)  # (smooth_left_copy + smooth_right_copy) / 2

        _, _, N = x_enc.shape
        enc_out = self.enc_embedding(x_enc, None)
        enc_out, attns = self.encoder(enc_out)#, attn_mask=None)

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

        '''
        dec_out = self.projection(enc_out).permute(0, 2, 1)[:, :, :N]

        # De-Normalization from Non-stationary Transformer
        if self.use_norm:
            dec_out = dec_out * (stdev[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))
            dec_out = dec_out + (means[:, 0, :].unsqueeze(1).repeat(1, self.h, 1))
        return dec_out
        '''

    def estimate_frequency(self, data):
        # Estimate frequency using FFT (Fast Fourier Transform)
        fft_result = torch.fft.rfft(data, dim=1)
        # Take the magnitude of the frequencies
        frequencies = torch.abs(fft_result)
        # Calculate average frequency magnitude
        avg_frequency = torch.mean(frequencies, dim=1)
        return avg_frequency

    def normalize_frequencies(self, data, target_frequency):
        # Estimate the frequency of each sequence
        frequencies = self.estimate_frequency(data)

        # Calculate scaling factors based on how far each sequence is from the target frequency
        scaling_factors = frequencies / target_frequency

        # Apply Gaussian filter with inverse scaling factor (stronger smoothing for higher frequency sequences)
        length = data.size(1)
        for i in range(data.size(0)):
            sigma = 1.0 / scaling_factors[i].item() if scaling_factors[i].numel() == 1 else 1.0 / scaling_factors[i][
                0].item()  # Handle the case of multi-element tensors
            data[i, :, :] = self.gaussian_filter(data[i:i + 1, :, :], sigma=sigma)

        return data

    def normalize_frequencies2(self, data, target_frequency):
        # Estimate the frequency of each sequence
        frequencies = self.estimate_frequency(data)

        # Calculate scaling factors based on how far each sequence is from the target frequency
        scaling_factors = frequencies / target_frequency

        # Apply Gaussian filter with inverse scaling factor (stronger smoothing for higher frequency sequences)
        length = data.size(1)
        for i in range(data.size(0)):
            sigma = 1.0 / scaling_factors[i].item()  # Inverse of scaling factor
            data[i, :, :] = self.gaussian_filter(data[i:i + 1, :, :], sigma=sigma)

        return data

    def gaussian_filter(self, data, kernel_size=5, sigma=1.0):
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
                result[i, :, j] = F.conv1d(data[i, :, j].unsqueeze(0).unsqueeze(0),
                                           kernel, padding=kernel_size // 2).squeeze(0).squeeze(0)
        return result

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