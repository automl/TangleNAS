from lib.datasets import build_dataset
import argparse
import datetime
import numpy as np
import time
import torch
import torch.backends.cudnn as cudnn
import json
import yaml
import time
from random import randint
from pathlib import Path
from timm.data import Mixup
from timm.models import create_model
from timm.loss import LabelSmoothingCrossEntropy, SoftTargetCrossEntropy
from timm.scheduler import create_scheduler
from timm.utils import NativeScaler
from lib.datasets import build_dataset
from supernet_engine import train_one_epoch, evaluate
from lib.samplers import RASampler
from lib import utils
from lib.config import cfg, update_config_from_file
from search_spaces.AutoFormer.model_one_shot.supernet_transformer_search import Vision_TransformerSuper
import torch.nn as nn
import torch.nn.functional as F
import pickle
import pandas as pd
from architect import Architect
import warnings
from timm_optimizer import create_optimizer
import wandb
class ConcatDataset(torch.utils.data.Dataset):
    def __init__(self, *datasets):
        self.datasets = datasets

    def __getitem__(self, i):
        return tuple(d[i %len(d)] for d in self.datasets)

    def __len__(self):
        return max(len(d) for d in self.datasets)

def get_args_parser():
    parser = argparse.ArgumentParser(
        'AutoFormer training and evaluation script', add_help=False)
    parser.add_argument('--batch-size', default=2048, type=int)
    parser.add_argument('--epochs', default=300, type=int)
    # config file
    parser.add_argument('--cfg',
                        help='experiment configure file name',
                        required=True,
                        type=str)

    # custom parameters
    parser.add_argument('--platform',
                        default='pai',
                        type=str,
                        choices=['itp', 'pai', 'aml'],
                        help='Name of model to train')
    parser.add_argument('--teacher_model',
                        default='',
                        type=str,
                        help='Name of teacher model to train')
    parser.add_argument('--relative_position', action='store_true')
    parser.add_argument('--gp', action='store_true')
    parser.add_argument('--change_qkv', action='store_true')
    parser.add_argument('--max_relative_position',
                        type=int,
                        default=14,
                        help='max distance in relative position embedding')

    # Model parameters
    parser.add_argument('--model',
                        default='',
                        type=str,
                        metavar='MODEL',
                        help='Name of model to train')
    # AutoFormer config
    parser.add_argument('--mode',
                        type=str,
                        default='super',
                        choices=['super', 'retrain'],
                        help='mode of AutoFormer')
    parser.add_argument('--input-size', default=224, type=int)
    parser.add_argument('--patch_size', default=16, type=int)

    parser.add_argument('--drop',
                        type=float,
                        default=0.0,
                        metavar='PCT',
                        help='Dropout rate (default: 0.)')
    parser.add_argument('--drop-path',
                        type=float,
                        default=0.1,
                        metavar='PCT',
                        help='Drop path rate (default: 0.1)')
    parser.add_argument('--drop-block',
                        type=float,
                        default=None,
                        metavar='PCT',
                        help='Drop block rate (default: None)')

    parser.add_argument('--model-ema', action='store_true')
    parser.add_argument('--no-model-ema',
                        action='store_false',
                        dest='model_ema')
    # parser.set_defaults(model_ema=True)
    parser.add_argument('--model-ema-decay',
                        type=float,
                        default=0.99996,
                        help='')
    parser.add_argument('--model-ema-force-cpu',
                        action='store_true',
                        default=False,
                        help='')
    parser.add_argument('--rpe_type',
                        type=str,
                        default='bias',
                        choices=['bias', 'direct'])
    parser.add_argument('--post_norm', action='store_true')
    parser.add_argument('--no_abs_pos', action='store_true')

    # Optimizer parameters
    parser.add_argument('--opt',
                        default='adamw',
                        type=str,
                        metavar='OPTIMIZER',
                        help='Optimizer (default: "adamw"')
    parser.add_argument('--opt-eps',
                        default=1e-8,
                        type=float,
                        metavar='EPSILON',
                        help='Optimizer Epsilon (default: 1e-8)')
    parser.add_argument(
        '--opt-betas',
        default=None,
        type=float,
        nargs='+',
        metavar='BETA',
        help='Optimizer Betas (default: None, use opt default)')
    parser.add_argument('--clip-grad',
                        type=float,
                        default=None,
                        metavar='NORM',
                        help='Clip gradient norm (default: None, no clipping)')
    parser.add_argument('--momentum',
                        type=float,
                        default=0.9,
                        metavar='M',
                        help='SGD momentum (default: 0.9)')
    parser.add_argument('--weight-decay',
                        type=float,
                        default=0.05,
                        help='weight decay (default: 0.05)')

    # Learning rate schedule parameters
    parser.add_argument('--sched',
                        default='cosine',
                        type=str,
                        metavar='SCHEDULER',
                        help='LR scheduler (default: "cosine"')
    parser.add_argument('--lr',
                        type=float,
                        default=5e-4,
                        metavar='LR',
                        help='learning rate (default: 5e-4)')
    parser.add_argument('--lr-noise',
                        type=float,
                        nargs='+',
                        default=None,
                        metavar='pct, pct',
                        help='learning rate noise on/off epoch percentages')
    parser.add_argument(
        '--lr-noise-pct',
        type=float,
        default=0.67,
        metavar='PERCENT',
        help='learning rate noise limit percent (default: 0.67)')
    parser.add_argument('--lr-noise-std',
                        type=float,
                        default=1.0,
                        metavar='STDDEV',
                        help='learning rate noise std-dev (default: 1.0)')
    parser.add_argument('--warmup-lr',
                        type=float,
                        default=1e-6,
                        metavar='LR',
                        help='warmup learning rate (default: 1e-6)')
    parser.add_argument(
        '--min-lr',
        type=float,
        default=1e-5,
        metavar='LR',
        help='lower lr bound for cyclic schedulers that hit 0 (1e-5)')
    parser.add_argument('--lr-power',
                        type=float,
                        default=1.0,
                        help='power of the polynomial lr scheduler')

    parser.add_argument('--decay-epochs',
                        type=float,
                        default=30,
                        metavar='N',
                        help='epoch interval to decay LR')
    parser.add_argument('--warmup-epochs',
                        type=int,
                        default=5,
                        metavar='N',
                        help='epochs to warmup LR, if scheduler supports')
    parser.add_argument(
        '--cooldown-epochs',
        type=int,
        default=10,
        metavar='N',
        help='epochs to cooldown LR at min_lr, after cyclic schedule ends')
    parser.add_argument(
        '--patience-epochs',
        type=int,
        default=10,
        metavar='N',
        help='patience epochs for Plateau LR scheduler (default: 10')
    parser.add_argument('--decay-rate',
                        '--dr',
                        type=float,
                        default=0.1,
                        metavar='RATE',
                        help='LR decay rate (default: 0.1)')

    # Augmentation parameters
    parser.add_argument('--color-jitter',
                        type=float,
                        default=0.4,
                        metavar='PCT',
                        help='Color jitter factor (default: 0.4)')
    parser.add_argument('--aa',
                        type=str,
                        default='rand-m9-mstd0.5-inc1',
                        metavar='NAME',
                        help='Use AutoAugment policy. "v0" or "original". " + \
                             "(default: rand-m9-mstd0.5-inc1)'),
    parser.add_argument('--smoothing',
                        type=float,
                        default=0.1,
                        help='Label smoothing (default: 0.1)')
    parser.add_argument(
        '--train-interpolation',
        type=str,
        default='bicubic',
        help=
        'Training interpolation (random, bilinear, bicubic default: "bicubic")'
    )

    parser.add_argument('--repeated-aug', action='store_true')
    parser.add_argument('--no-repeated-aug',
                        action='store_false',
                        dest='repeated_aug')

    parser.set_defaults(repeated_aug=True)

    # * Random Erase params
    parser.add_argument('--reprob',
                        type=float,
                        default=0.25,
                        metavar='PCT',
                        help='Random erase prob (default: 0.25)')
    parser.add_argument('--remode',
                        type=str,
                        default='pixel',
                        help='Random erase mode (default: "pixel")')
    parser.add_argument('--recount',
                        type=int,
                        default=1,
                        help='Random erase count (default: 1)')
    parser.add_argument(
        '--re:qlit',
        action='store_true',
        default=False,
        help='Do not random erase first (clean) augmentation split')

    # * Mixup params
    parser.add_argument(
        '--mixup',
        type=float,
        default=0.8,
        help='mixup alpha, mixup enabled if > 0. (default: 0.8)')
    parser.add_argument(
        '--cutmix',
        type=float,
        default=1.0,
        help='cutmix alpha, cutmix enabled if > 0. (default: 1.0)')
    parser.add_argument(
        '--cutmix-minmax',
        type=float,
        nargs='+',
        default=None,
        help=
        'cutmix min/max ratio, overrides alpha and enables cutmix if set (default: None)'
    )
    parser.add_argument(
        '--mixup-prob',
        type=float,
        default=1.0,
        help=
        'Probability of performing mixup or cutmix when either/both is enabled'
    )
    parser.add_argument(
        '--mixup-switch-prob',
        type=float,
        default=0.5,
        help=
        'Probability of switching to cutmix when both mixup and cutmix enabled'
    )
    parser.add_argument(
        '--mixup-mode',
        type=str,
        default='batch',
        help='How to apply mixup/cutmix params. Per "batch", "pair", or "elem"'
    )

    # Dataset parameters
    parser.add_argument(
        '--data-path',
        default=
        'imagenet/',
        type=str,
        help='dataset path')
    parser.add_argument('--data-set',
                        default='CIFAR10',
                        choices=['CIFAR100','CIFAR10','CIFAR', 'IMNET', 'INAT', 'INAT19'],
                        type=str,
                        help='Image Net dataset path')
    parser.add_argument('--inat-category',
                        default='name',
                        choices=[
                            'kingdom', 'phylum', 'class', 'order',
                            'supercategory', 'family', 'genus', 'name'
                        ],
                        type=str,
                        help='semantic granularity')

    parser.add_argument('--output_dir',
                        default='./',
                        help='path where to save, empty for no saving')
    parser.add_argument('--device',
                        default='cuda',
                        help='device to use for training / testing')
    parser.add_argument('--seed', default=0, type=int)
    parser.add_argument('--resume', default='', help='resume from checkpoint')
    parser.add_argument('--start_epoch',
                        default=0,
                        type=int,
                        metavar='N',
                        help='start epoch')
    parser.add_argument('--eval',
                        action='store_true',
                        help='Perform evaluation only')
    parser.add_argument('--prior',
                        action='store_true',
                        help='Use optimizer with prior')
    parser.add_argument('--num_workers', default=10, type=int)
    parser.add_argument('--dist-eval',
                        action='store_true',
                        default=False,
                        help='Enabling distributed evaluation')
    parser.add_argument(
        '--pin-mem',
        action='store_true',
        help=
        'Pin CPU memory in DataLoader for more efficient (sometimes) transfer to GPU.'
    )
    parser.add_argument('--no-pin-mem',
                        action='store_false',
                        dest='pin_mem',
                        help='')
    parser.set_defaults(pin_mem=True)

    # distributed training parameters
    parser.add_argument('--world_size',
                        default=1,
                        type=int,
                        help='number of distributed processes')
    parser.add_argument('--dist_url',
                        default='env://',
                        help='url used to set up distributed training')

    parser.add_argument('--amp', action='store_true')
    parser.add_argument('--no-amp', action='store_false', dest='amp')
    parser.add_argument('--arch_learning_rate',
                        type=float,
                        default=3e-4,
                        metavar='LR',
                        help='learning rate for arch encoding')
    parser.add_argument('--arch_weight_decay',
                        type=float,
                        default=1e-3,
                        metavar='LR',
                        help='weight decay for arch encoding')
    parser.add_argument('--local_rank',
                        default=-1,
                        type=int,
                        help='local rank for distributed training')
    parser.add_argument('--unrolled',
                        action='store_true',
                        default=False,
                        help='use one-step unrolled validation loss')
    parser.add_argument('--use_we_v2',
                        action='store_true',
                        default=False,
                        help='Use we v2')
    parser.set_defaults(amp=True)

    #one shot optimizer args
    parser.add_argument('--tau_max', default=10, type=int, help='Tau max')
    parser.add_argument('--tau_min', default=0.1, type=int, help='Tau min')
    parser.add_argument('--one_shot_opt',
                        default="darts",
                        type=str,
                        help='Tau min')

    # Random Search parameters
    parser.add_argument('--search_iters',
                        default=100,
                        type=int,
                        help='Number of iterations of search to perform')

    parser.add_argument(
        '--dataset-subset-size',
        default=150,
        type=int,
        help=
        'Size of the dataset which should be used for evaluation in the search phase'
    )

    parser.add_argument(
        '--sample-with-priors',
        default=False,
        action='store_true',
        help=
        'If set to true, samples configs with probabilities as defined by the alpha weights'
    )

    parser.add_argument(
        '--model-path',
        default='./checkpoints/checkpoint_darts_cifar100.pth',
        type=str,
        help='Path to file with weights of trained supernetwork')

    parser.add_argument('--ratio',
                        default=0.5,
                        type=float,
                        help='train val split portion')

    return parser

parser = argparse.ArgumentParser(
        'AutoFormer training and evaluation script',
        parents=[get_args_parser()])

args = parser.parse_args()
dataset_train, args.nb_classes = build_dataset(is_train=True, args=args)
data_path = "/gpfs/bwfor/work/ws/fr_rs1131-tanglenas/imagenet/"
dataset_test, _ = build_dataset(is_train=False, args=args)
ratio = args.ratio
len_train = int((ratio) * len(dataset_train))
len_val = len(dataset_train) - len_train
data_path  = "/gpfs/bwfor/work/ws/fr_rs1131-tanglenas/subImageNet"
dataset_val, _ = build_dataset(is_train= True, args=args, data_path=data_path)
sampler_train = torch.utils.data.DistributedSampler(
                ConcatDataset(dataset_train,dataset_val),
                num_replicas=3,
                rank=0,
                shuffle=True)


data_loader_train = torch.utils.data.DataLoader(
        ConcatDataset(dataset_train,dataset_val),
        sampler=sampler_train,
        batch_size=args.batch_size,
        num_workers=0,
        pin_memory=args.pin_mem,
        drop_last=True
    )
for i, (batch1, batch2) in enumerate(data_loader_train):
    input,target = batch1
    input_search, target_search  = batch2
    print(input_search.shape)
    print(target_search.shape)
    print(input.shape)
    print(target.shape)
    #print(torch.allclose(input_search,input))
    #assert  ~torch.allclose(input_search,input)
    #assert ~torch.allclose(target_search,target)
