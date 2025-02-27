import torch
import torch.nn as nn
import torch.optim as optim
import pytorch_lightning as pl
from energy_net.data_sampler import Sampler


class Swish(nn.Module):
    def forward(self, x):
        return x * torch.sigmoid(x)


class CNNModel(nn.Module):
    def __init__(self, hidden_features=32, out_dim=1, **kwargs):
        super(CNNModel, self).__init__()
        c_hid1 = hidden_features // 2
        c_hid2 = hidden_features
        c_hid3 = hidden_features*2

        self.cnn_layers = nn.Sequential(
            nn.Conv2d(1, c_hid1, kernel_size=5, stride=2, padding=4),  # (28 + 2*padding - kernel_size)/stride + 1 = 16
            Swish(),
            nn.Conv2d(c_hid1, c_hid2, kernel_size=3, stride=2, padding=1),  # 8*8
            Swish(),
            nn.Conv2d(c_hid2, c_hid3, kernel_size=3, stride=2, padding=1),  # 4*4
            Swish(),
            nn.Conv2d(c_hid3, c_hid3, kernel_size=3, stride=2, padding=1),  # 2*2
            Swish(),
            nn.Flatten(),
            nn.Linear(c_hid3*4, c_hid3),
            Swish(),
            nn.Linear(c_hid3, out_dim)
        )

    def forward(self, x):
        return self.cnn_layers(x).squeeze(dim=-1)


class DeepEnergyModel(pl.LightningModule):
    def __init__(self, img_shape, batch_size, alpha=0.1, lr=1e-4, beta1=0.0, **cnn_args):
        super().__init__()
        self.save_hyperparameters()
        self.model = CNNModel(**cnn_args)  # the cnn model denotes -E_theta
        self.sampler = Sampler(self.model, img_shape, batch_size)
        self.example_input_array = torch.zeros(1, *img_shape)

    def forward(self, x):
        return self.model(x)

    def configure_optimizers(self):
        # Energy models can have issues with momentum as the loss surfaces changes with its parameters.
        # Hence, we set it to 0 by default.
        optimizer = optim.Adam(self.parameters(), lr=self.hparams.lr, betas=(self.hparams.beta1, 0.999))
        scheduler = optim.lr_scheduler.StepLR(optimizer, 1, gamma=0.97)  # Exponential decay over epochs
        return [optimizer], [scheduler]

    def training_step(self, batch, batch_idx, device="cpu"):
        real_imgs, _ = batch
        small_noise = torch.randn_like(real_imgs) * 0.005
        real_imgs.add_(small_noise).clamp_(min=-1.0, max=1.0)

        fake_imgs = self.sampler.sample_new_examples(steps=60, step_size=10, device=device)

        # predict energy score for all images
        imp_imgs = torch.cat([real_imgs, fake_imgs], dim=0)
        real_out, fake_out = self.model(imp_imgs).chunk(2, dim=0)  # real size = fake size, split into two pieces evenly

        # calculate the loss
        reg_loss = self.hparams.alpha * (real_out**2 + fake_out**2).mean()
        cdiv_loss = (fake_out - real_out).mean()
        loss = reg_loss + cdiv_loss

        # logging
        self.log('loss', loss)
        self.log('loss_regularization', reg_loss)
        self.log('loss_contrastive_divergence', cdiv_loss)
        self.log('metrics_avg_real', real_out.mean())
        self.log('metrics_avg_fake', fake_out.mean())
        return loss

    def validation_step(self, batch, batch_idx):
        # For validating, we calculate the contrastive divergence between purely random images and unseen examples
        # Note that the validation/test step of energy-based models depends on what we are interested in the model
        real_imgs, _ = batch
        fake_imgs = torch.rand_like(real_imgs) * 2 - 1

        inp_imgs = torch.cat([real_imgs, fake_imgs], dim=0)
        real_out, fake_out = self.model(inp_imgs).chunk(2, dim=0)

        cdiv = fake_out.mean() - real_out.mean()
        self.log('val_contrastive_divergence', cdiv)
        self.log('val_fake_out', fake_out.mean())
        self.log('val_real_out', real_out.mean())


















