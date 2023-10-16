import collections
from copy import deepcopy

import numpy as np
import matplotlib.pyplot as plt

import argparse

import torch

import contextlib
import pickle
import random

import numpy as np
import time
import torch
import torch.backends.cudnn as cudnn
from pathlib import Path
import argparse
import os
import yaml
# Encoder: take a string, output a list of integers
import torch.nn as nn
import torch.nn.functional as F
import torch
import torchvision
import torchvision.transforms as transforms
import torch.optim as optim
import numpy as np
import pickle
import argparse
from toy_search_spaces.cell_topology.model_search_temp import ToyCellSearchSpace
from toy_search_spaces.cell_topology.utils import spos_search_dataloader
#print(len(eval_data))
def decode_cand_tuple(cand_tuple):
    channel_size_1 = cand_tuple[0]
    channel_size_2 = cand_tuple[1]
    channel_size_3 = cand_tuple[2]
    channel_size_4 = cand_tuple[3]
    kernel_size_1 = cand_tuple[4]
    kernel_size_2 = cand_tuple[5]
    kernel_size_3 = cand_tuple[6]
    kernel_size_4 = cand_tuple[7]
    return kernel_size_1, kernel_size_2, kernel_size_3, kernel_size_4, channel_size_1, channel_size_2, channel_size_3, channel_size_4

class EvolutionSearcher(object):

    def __init__(self, args, device, model, model_without_ddp, output_dir, train_loader, valid_loader, test_loader):
        self.device = device
        self.model = model
        self.model_without_ddp = model_without_ddp
        self.args = args
        self.max_epochs = args.max_epochs
        self.select_num = args.select_num
        self.population_num = args.population_num
        self.m_prob = args.m_prob
        self.crossover_num = args.crossover_num
        self.mutation_num = args.mutation_num
        self.parameters_limits = args.param_limits
        self.min_parameters_limits = args.min_param_limits
        self.output_dir = output_dir
        self.s_prob =args.s_prob
        self.vis_dict = {}
        self.keep_top_k = {self.select_num: [], 50: []}
        self.epoch = 0
        self.checkpoint_path = args.resume
        self.eval_iters = 200
        self.candidates = []
        self.top_losses = []
        self.cand_params = []
        self.arch_params = []
        self.cand_to_arch = {}
        self.train_loader = train_loader
        self.valid_loader = valid_loader
        self.test_loader = test_loader

    def save_checkpoint(self):

        info = {}
        info['top_accs'] = self.top_losses
        info['candidates'] = self.candidates
        info['vis_dict'] = self.vis_dict
        info['keep_top_k'] = self.keep_top_k
        info['epoch'] = self.epoch
        checkpoint_path = os.path.join(self.output_dir, "checkpoint-{}.pth.tar".format(self.epoch))
        torch.save(info, checkpoint_path)
        print('save checkpoint to', checkpoint_path)

    def load_checkpoint(self):
        if not os.path.exists(self.checkpoint_path):
            return False
        info = torch.load(self.checkpoint_path)
        self.candidates = info['candidates']
        self.vis_dict = info['vis_dict']
        self.keep_top_k = info['keep_top_k']
        self.epoch = info['epoch']

        print('load checkpoint from', self.checkpoint_path)
        return True

    def is_legal(self, cand, arch):
        assert isinstance(cand, str)
        if cand not in self.vis_dict:
            self.vis_dict[cand] = {}
        info = self.vis_dict[cand]
        if 'visited' in info:
            return False
        eval_acc, test_acc = self.estimate_acc(arch, self.model)

        info['eval_acc'] = eval_acc
        info['test_acc'] = test_acc

        info['visited'] = True
        self.cand_to_arch[cand] = arch

        return True

    def estimate_acc(self, config, model):
        correct = 0
        total = 0
        # since we're not training, we don't need to calculate the gradients for our outputs
        with torch.no_grad():
         for data in self.valid_loader:
            images, labels = data
            images = images.cuda()
            labels = labels.cuda()
            # calculate outputs by running images through the network
            _, outputs = model(images, alphas=config)
            # the class with the highest energy is what we choose as prediction
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
        val_acc =  100 * correct / total
        correct = 0
        total = 0
        with torch.no_grad():
            for data in self.test_loader:
                images, labels = data
                images = images.cuda()
                labels = labels.cuda()
                # calculate outputs by running images through the network
                _, outputs = model(images, alphas=config)
                # the class with the highest energy is what we choose as prediction
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        test_acc =  100 * correct / total
        return val_acc, test_acc
        
    
    def update_top_k(self, candidates, *, k, key, reverse=False):
        assert k in self.keep_top_k
        print('select ......')
        t = self.keep_top_k[k]
        t += candidates
        t.sort(key=key, reverse=reverse)
        self.keep_top_k[k] = t[:k]

    def stack_random_cand(self, random_func, *, batchsize=100):
        while True:
            cands = []
            arch_params = []
            for _ in range(batchsize):
                cand, arch_sampled = random_func()
                cands.append(cand)
                arch_params.append(arch_sampled)
            for cand in cands:
                if str(cand) not in self.vis_dict:
                    self.vis_dict[str(cand)] = {}
                info = self.vis_dict[str(cand)]
            return cands, arch_params

    def get_random_cand(self):
        alpha_sampled = self.model.sampler.sample_step(self.model._arch_parameters) 
        genotype = self.model.genotype(alphas=alpha_sampled)
        candidate = genotype

        return candidate, alpha_sampled

    def get_random(self, num):
        print('random select ........')
        cand_iter, arch_iter = self.stack_random_cand(self.get_random_cand)
        i = 0
        while len(self.candidates) < num:
            cand = cand_iter[i]
            arch_param = arch_iter[i]
            if not self.is_legal(str(cand),arch_param):
                i += 1
                continue
            self.candidates.append(str(cand))
            self.arch_params.append(arch_param)
            print('random {}/{}'.format(len(self.candidates), num))
            i += 1
        print('random_num = {}'.format(len(self.candidates)))

    def get_mutation(self, k, mutation_num, m_prob, s_prob):
        assert k in self.keep_top_k
        print('mutation ......')
        res = []
        res_arch = []
        iter = 0
        max_iters = mutation_num * 10

        def random_func():
            # Choose a random candidate
            cand = random.choice(self.keep_top_k[k])
            arch_param = self.cand_to_arch[cand]
     
            # mutated candidate
            result_arch_param = self.model.mutate(arch_param, m_prob)
            result_cand = self.model.genotype(alphas=result_arch_param)
            return result_cand, result_arch_param

        cand_iter, arch_iter = self.stack_random_cand(random_func)
        i = 0
        while len(res) < mutation_num and max_iters > 0:
            max_iters -= 1
            cand = cand_iter[i]
            arch_param = arch_iter[i]
            if not self.is_legal(str(cand), arch_param):
                i += 1
                continue
            res.append(str(cand))
            res_arch.append(arch_param)
            print('mutation {}/{}'.format(len(res), mutation_num))
            i += 1

        print('mutation_num = {}'.format(len(res)))
        return res

    def get_crossover(self, k, crossover_num):
        assert k in self.keep_top_k
        print('crossover ......')
        res_cand = []
        res_arch = []
        max_iters = 10 * crossover_num

        def random_func():

            # choose parent 1 (p1) and parent 2 (p2) randomly from top k
            p1 = random.choice(self.keep_top_k[k])
            p2 = random.choice(self.keep_top_k[k])
            p1_arch_param = self.cand_to_arch[p1]
            p2_arch_param = self.cand_to_arch[p2]
            # crossover
            result_arch_param = self.model.crossover(p1_arch_param, p2_arch_param)
            result_cand = self.model.genotype(alphas=result_arch_param)
            return result_cand, result_arch_param

        cand_iter, arch_iter = self.stack_random_cand(random_func)
        i = 0
        while len(res_cand) < crossover_num and max_iters > 0:
            max_iters -= 1
            cand = cand_iter[i]
            if not self.is_legal(str(cand), arch_iter[i]):
                i  = i +1 
                continue
            res_cand.append(str(cand))
            res_arch.append(arch_iter[i])
            print('crossover {}/{}'.format(len(res_cand), crossover_num))
            i += 1

        print('crossover_num = {}'.format(len(res_cand)))
        return res_cand

    def search(self):
        print(
            'population_num = {} select_num = {} mutation_num = {} crossover_num = {} random_num = {} max_epochs = {}'.format(
                self.population_num, self.select_num, self.mutation_num, self.crossover_num,
                self.population_num - self.mutation_num - self.crossover_num, self.max_epochs))

        # self.load_checkpoint()

        self.get_random(self.population_num)

        while self.epoch < self.max_epochs:
            print('epoch = {}'.format(self.epoch))

            self.update_top_k(
                self.candidates, k=self.select_num, key=lambda x: self.vis_dict[x]['eval_acc'],reverse=True)
            self.update_top_k(
                self.candidates, k=50, key=lambda x: self.vis_dict[x]['eval_acc'], reverse=True)

            print('epoch = {} : top {} result'.format(
                self.epoch, len(self.keep_top_k[50])))
            tmp_accuracy = []
            for i, cand in enumerate(self.keep_top_k[50]):
                print('No.{} {} Top-1 val acc = {}, Top-1 test acc = {}, params = {}'.format(
                    i + 1, cand, self.vis_dict[cand]['eval_acc'], self.vis_dict[cand]['test_acc'], 0))
                tmp_accuracy.append(self.vis_dict[cand]['eval_acc'])
            self.top_losses.append(tmp_accuracy)

            mutation_cands = self.get_mutation(
                self.select_num, self.mutation_num, self.m_prob, self.s_prob)
            crossover_cands = self.get_crossover(self.select_num, self.crossover_num)

            self.candidates = mutation_cands + crossover_cands

            self.get_random(self.population_num)

            self.epoch += 1

            self.save_checkpoint()

def get_args_parser():
    parser = argparse.ArgumentParser('DeiT training and evaluation script', add_help=False)
    parser.add_argument('--batch-size', default=64, type=int)

    # evolution search parameters
    parser.add_argument('--max-epochs', type=int, default=1000)
    parser.add_argument('--select-num', type=int, default=10)
    parser.add_argument('--population-num', type=int, default=5) #30
    parser.add_argument('--m_prob', type=float, default=0.2)
    parser.add_argument('--s_prob', type=float, default=0.4)
    parser.add_argument('--crossover-num', type=int, default=2) # 10 
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--mutation-num', type=int, default=2)
    parser.add_argument('--param-limits', type=float, default=10000000)
    parser.add_argument('--min-param-limits', type=float, default=0)


    # custom parameters
    parser.add_argument('--platform', default='pai', type=str, choices=['itp', 'pai', 'aml'],
                        help='Name of model to train')
    parser.add_argument('--teacher_model', default='', type=str,
                        help='Name of teacher model to train')
    parser.add_argument('--relative_position', action='store_true')
    parser.add_argument('--max_relative_position', type=int, default=14, help='max distance in relative position embedding')
    parser.add_argument('--scale', action='store_true')
    parser.add_argument('--gp', action='store_true')
    parser.add_argument('--change_qkv', action='store_true')

    # Model parameters
    parser.add_argument('--model', default='', type=str, metavar='MODEL',
                        help='Name of model to train')

    parser.add_argument('--input-size', default=224, type=int)
    parser.add_argument('--patch_size', default=16, type=int)

    parser.add_argument('--drop', type=float, default=0.0, metavar='PCT',
                        help='Dropout rate (default: 0.)')
    parser.add_argument('--drop-path', type=float, default=0.1, metavar='PCT',
                        help='Drop path rate (default: 0.1)')
    parser.add_argument('--drop-block', type=float, default=None, metavar='PCT',
                        help='Drop block rate (default: None)')

    parser.add_argument('--model-ema', action='store_true')
    parser.add_argument('--no-model-ema', action='store_false', dest='model_ema')
    # parser.set_defaults(model_ema=True)
    parser.add_argument('--model-ema-decay', type=float, default=0.99996, help='')
    parser.add_argument('--model-ema-force-cpu', action='store_true', default=False, help='')

    # custom model argument
    parser.add_argument('--rpe_type', type=str, default='bias', choices=['bias', 'direct'])
    parser.add_argument('--post_norm', action='store_true')
    parser.add_argument('--no_abs_pos', action='store_true')

    # Optimizer parameters
    parser.add_argument('--opt', default='adamw', type=str, metavar='OPTIMIZER',
                        help='Optimizer (default: "adamw"')
    parser.add_argument('--opt-eps', default=1e-8, type=float, metavar='EPSILON',
                        help='Optimizer Epsilon (default: 1e-8)')
    parser.add_argument('--opt-betas', default=None, type=float, nargs='+', metavar='BETA',
                        help='Optimizer Betas (default: None, use opt default)')
    parser.add_argument('--clip-grad', type=float, default=None, metavar='NORM',
                        help='Clip gradient norm (default: None, no clipping)')
    parser.add_argument('--momentum', type=float, default=0.9, metavar='M',
                        help='SGD momentum (default: 0.9)')
    parser.add_argument('--weight-decay', type=float, default=0.05,
                        help='weight decay (default: 0.05)')
    # Learning rate schedule parameters
    parser.add_argument('--sched', default='cosine', type=str, metavar='SCHEDULER',
                        help='LR scheduler (default: "cosine"')
    parser.add_argument('--lr', type=float, default=5e-4, metavar='LR',
                        help='learning rate (default: 5e-4)')
    parser.add_argument('--lr-noise', type=float, nargs='+', default=None, metavar='pct, pct',
                        help='learning rate noise on/off epoch percentages')
    parser.add_argument('--lr-noise-pct', type=float, default=0.67, metavar='PERCENT',
                        help='learning rate noise limit percent (default: 0.67)')
    parser.add_argument('--lr-noise-std', type=float, default=1.0, metavar='STDDEV',
                        help='learning rate noise std-dev (default: 1.0)')
    parser.add_argument('--warmup-lr', type=float, default=1e-6, metavar='LR',
                        help='warmup learning rate (default: 1e-6)')
    parser.add_argument('--min-lr', type=float, default=1e-5, metavar='LR',
                        help='lower lr bound for cyclic schedulers that hit 0 (1e-5)')
    parser.add_argument('--lr-power', type=float, default=1.0,
                        help='power of the polynomial lr scheduler')

    parser.add_argument('--decay-epochs', type=float, default=30, metavar='N',
                        help='epoch interval to decay LR')
    parser.add_argument('--warmup-epochs', type=int, default=5, metavar='N',
                        help='epochs to warmup LR, if scheduler supports')
    parser.add_argument('--cooldown-epochs', type=int, default=10, metavar='N',
                        help='epochs to cooldown LR at min_lr, after cyclic schedule ends')
    parser.add_argument('--patience-epochs', type=int, default=10, metavar='N',
                        help='patience epochs for Plateau LR scheduler (default: 10')
    parser.add_argument('--decay-rate', '--dr', type=float, default=0.1, metavar='RATE',
                        help='LR decay rate (default: 0.1)')

    # Augmentation parameters
    parser.add_argument('--color-jitter', type=float, default=0.4, metavar='PCT',
                        help='Color jitter factor (default: 0.4)')
    parser.add_argument('--aa', type=str, default='rand-m9-mstd0.5-inc1', metavar='NAME',
                        help='Use AutoAugment policy. "v0" or "original". " + \
                             "(default: rand-m9-mstd0.5-inc1)'),
    parser.add_argument('--smoothing', type=float, default=0.1, help='Label smoothing (default: 0.1)')
    parser.add_argument('--train-interpolation', type=str, default='bicubic',
                        help='Training interpolation (random, bilinear, bicubic default: "bicubic")')

    parser.add_argument('--repeated-aug', action='store_true')
    parser.add_argument('--no-repeated-aug', action='store_false', dest='repeated_aug')
    parser.set_defaults(repeated_aug=True)

    # * Random Erase params
    parser.add_argument('--reprob', type=float, default=0.25, metavar='PCT',
                        help='Random erase prob (default: 0.25)')
    parser.add_argument('--remode', type=str, default='pixel',
                        help='Random erase mode (default: "pixel")')
    parser.add_argument('--recount', type=int, default=1,
                        help='Random erase count (default: 1)')
    parser.add_argument('--resplit', action='store_true', default=False,
                        help='Do not random erase first (clean) augmentation split')

    # * Mixup params
    parser.add_argument('--mixup', type=float, default=0.8,
                        help='mixup alpha, mixup enabled if > 0. (default: 0.8)')
    parser.add_argument('--cutmix', type=float, default=1.0,
                        help='cutmix alpha, cutmix enabled if > 0. (default: 1.0)')
    parser.add_argument('--cutmix-minmax', type=float, nargs='+', default=None,
                        help='cutmix min/max ratio, overrides alpha and enables cutmix if set (default: None)')
    parser.add_argument('--mixup-prob', type=float, default=1.0,
                        help='Probability of performing mixup or cutmix when either/both is enabled')
    parser.add_argument('--mixup-switch-prob', type=float, default=0.5,
                        help='Probability of switching to cutmix when both mixup and cutmix enabled')
    parser.add_argument('--mixup-mode', type=str, default='batch',
                        help='How to apply mixup/cutmix params. Per "batch", "pair", or "elem"')

    # Dataset parameters
    parser.add_argument('--data-path', default='/datasets01_101/imagenet_full_size/061417/', type=str,
                        help='dataset path')
    parser.add_argument('--data-set', default='IMNET', choices=['CIFAR', 'IMNET', 'INAT', 'INAT19', 'EVO_IMNET'],
                        type=str, help='Image Net dataset path')
    parser.add_argument('--inat-category', default='name',
                        choices=['kingdom', 'phylum', 'class', 'order', 'supercategory', 'family', 'genus', 'name'],
                        type=str, help='semantic granularity')
    parser.add_argument('--no-prefetcher', action='store_true', default=False,
                        help='disable fast prefetcher')
    parser.add_argument('--output_dir', default='evo_checkpoint_conv_macro',
                        help='path where to save, empty for no saving')
    parser.add_argument('--device', default='cuda',
                        help='device to use for training / testing')
    parser.add_argument('--seed', default=0, type=int)
    parser.add_argument('--resume', default='', help='resume from checkpoint')
    parser.add_argument('--start_epoch', default=0, type=int, metavar='N',
                        help='start epoch')
    parser.add_argument('--eval', action='store_true', help='Perform evaluation only')
    parser.add_argument('--num_workers', default=10, type=int)
    parser.add_argument('--dist-eval', action='store_true', default=False, help='Enabling distributed evaluation')
    parser.add_argument('--pin-mem', action='store_true',
                        help='Pin CPU memory in DataLoader for more efficient (sometimes) transfer to GPU.')
    parser.add_argument('--no-pin-mem', action='store_false', dest='pin_mem',
                        help='')
    parser.set_defaults(pin_mem=True)

    # distributed training parameters
    parser.add_argument('--world_size', default=1, type=int,
                        help='number of distributed processes')
    parser.add_argument('--dist_url', default='env://', help='url used to set up distributed training')
    parser.add_argument('--amp', action='store_true')
    parser.add_argument('--no-amp', action='store_false', dest='amp')
    parser.add_argument('--train_portion', default=0.8, type=float, help='portion of training data')
    parser.add_argument('--model_path', default='/work/dlclarge2/sukthank-tanglenas/merge/TangleNAS-dev/out_train_spos_spos_9004_0.8/ckpt.pt', type=str, help='path to pretrained model')
    parser.set_defaults(amp=True)

    return parser

def main(args):

    device = torch.device(args.device)

    print(args)
    args_text = yaml.safe_dump(args.__dict__, default_flow_style=False)
    # save config for later experiments
    with open(os.path.join(args.output_dir, "config.yaml"), 'w') as f:
        f.write(args_text)
    # fix the seed for reproducibility

    seed = args.seed
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(args.seed)
    cudnn.benchmark = True
    print(f"Creating Toy Cell Entangled Model")
    model_path = args.model_path
    model_name  = model_path.split("/")[-2]
    args.output_dir = os.path.join(args.output_dir, model_name)
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    model = ToyCellSearchSpace("spos",10,criterion=torch.nn.CrossEntropyLoss(),entangle_weights=True, use_we_v2=True)
    model.load_state_dict(torch.load(model_path)["search_model"])

    model.to(device)
    model_without_ddp = model


    n_parameters = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print('number of params:', n_parameters)


    t = time.time()
    train_loader, val_loader, test_loader = spos_search_dataloader(train_portion=args.train_portion)
    searcher = EvolutionSearcher(args, device, model, model_without_ddp, args.output_dir, train_loader, val_loader, test_loader)

    searcher.search()

    print('total searching time = {:.2f} hours'.format(
        (time.time() - t) / 3600))


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Toy cell entangled evolution search', parents=[get_args_parser()])
    args = parser.parse_args()
    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    main(args)