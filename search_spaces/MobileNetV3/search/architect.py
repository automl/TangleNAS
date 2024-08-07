import torch
import numpy as np
import torch.nn as nn
from torch.autograd import Variable
from torch.distributions.dirichlet import Dirichlet
from torch.distributions.kl import kl_divergence
import torch.nn.functional as F


def get_contributing_params(y, top_level=True):
    nf = y.grad_fn.next_functions if top_level else y.next_functions
    for f, _ in nf:
        try:
            yield f.variable
        except AttributeError:
            pass  # node has no tensor
        if f is not None:
            yield from get_contributing_params(f, top_level=False)


def _concat(xs):
    return torch.cat([x.view(-1) for x in xs])


def get_contributing_params(y, top_level=True):
    nf = y.grad_fn.next_functions if top_level else y.next_functions
    for f, _ in nf:
        try:
            yield f.variable
        except AttributeError:
            pass  # node has no tensor
        if f is not None:
            yield from get_contributing_params(f, top_level=False)


class Architect(object):

    def __init__(self, model, args):
        self.network_momentum = args.momentum
        self.network_weight_decay = args.weight_decay

        if isinstance(model, torch.nn.parallel.DistributedDataParallel):
            self.model = model.module
            self.ddp_model = model
        else:
            self.model = self.ddp_model = model

        self.optimizer = torch.optim.Adam(self.model.arch_parameters(),
                                          lr=args.arch_learning_rate,
                                          betas=(0.5, 0.999),
                                          weight_decay=args.arch_weight_decay)
        self.optimizer_os = args.one_shot_opt
        '''if self.optimizer_os == "drnas":
            self.anchor = Dirichlet(
                torch.ones_like(
                    torch.nn.utils.parameters_to_vector(
                        self.model.arch_parameters())))
            self.reg_scale = 1e-3'''

    def _compute_unrolled_model(self, input, target, eta, network_optimizer):
        input_labels = self.ddp_model(input)
        #print(input_labels.shape)
        #print(target.shape)
        loss = self.criterion(input_labels, target)
        #li=[]
        parameters = [
            p for n, p in self.model.named_parameters() if p.requires_grad
        ]
        theta = _concat(parameters).data
        try:
            moment = _concat(network_optimizer.state[v]['momentum_buffer']
                             for v in self.model.parameters()).mul_(
                                 self.network_momentum)
        except:
            moment = torch.zeros_like(theta)
        dtheta = _concat(torch.autograd.grad(
            loss, parameters)).data + self.network_weight_decay * theta
        unrolled_model = self._construct_model_from_theta(
            theta.sub(eta, moment + dtheta))
        return unrolled_model

    def _get_kl_reg(self):
        cons = (F.elu(
            torch.nn.utils.parameters_to_vector(self.model.arch_parameters()))
                + 1)
        q = Dirichlet(cons)
        p = self.anchor
        kl_reg = self.reg_scale * torch.sum(kl_divergence(q, p))
        return kl_reg

    def step(self, args, epoch, criterion, input_valid, target_valid, unrolled=False):
        self.criterion = criterion
        self.epoch = epoch
        self.optimizer.zero_grad()
        self.args = args
        self._backward_step(input_valid, target_valid)
        self.optimizer.step()

    def _backward_step(self, input_valid, target_valid):
        input_labels = self.ddp_model(input_valid)
        loss = self.criterion(input_labels, target_valid)  #+ 0.01 * reg
        loss.backward()
        #for v in self.model.arch_parameters():
        #    print(v.grad)

    def _backward_step_unrolled(self, input_train, target_train, input_valid,
                                target_valid, eta, network_optimizer):
        unrolled_model = self._compute_unrolled_model(input_train,
                                                      target_train, eta,
                                                      network_optimizer)
        input_labels = self.ddp_model(input_valid)
        unrolled_loss = self.criterion(input_labels, target_valid)

        unrolled_loss.backward()
        dalpha = [v.grad for v in unrolled_model.arch_parameters()]
        vector = [
            v.grad.data for v in [
                p for n, p in unrolled_model.named_parameters()
                if p.requires_grad
            ]
        ]

        implicit_grads = self._hessian_vector_product(vector, input_train,
                                                      target_train)

        for g, ig in zip(dalpha, implicit_grads):
            g.data.sub_(eta, ig.data)

        for v, g in zip(self.model.arch_parameters(), dalpha):
            if v.grad is None:
                v.grad = Variable(g.data)
            else:
                v.grad.data.copy_(g.data)

    def _construct_model_from_theta(self, theta):
        model_new = self.model.new()
        model_dict = self.model.state_dict()

        params, offset = {}, 0
        for k, v in self.model.named_parameters():
            v_length = np.prod(v.size())
            params[k] = theta[offset:offset + v_length].view(v.size())
            offset += v_length

        assert offset == len(theta)
        model_dict.update(params)
        model_new.load_state_dict(model_dict)
        return model_new.cuda()

    def _hessian_vector_product(self, vector, input, target, r=1e-2):
        R = r / _concat(vector).norm()
        for p, v in zip(self.model.parameters(), vector):
            p.data.add_(R, v)
        loss = self.criterion(input, target)
        grads_p = torch.autograd.grad(loss, self.model.arch_parameters())

        for p, v in zip(self.model.parameters(), vector):
            p.data.sub_(2 * R, v)
        out = self.ddp_model(input)
        loss = self.criterion(out, target)
        grads_n = torch.autograd.grad(loss, self.model.arch_parameters())

        for p, v in zip(self.model.parameters(), vector):
            p.data.add_(R, v)

        return [(x - y).div_(2 * R) for x, y in zip(grads_p, grads_n)]