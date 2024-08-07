import torch
import torch.nn as nn
import torch.nn.functional as F
from search_spaces.DARTS.net2wider import InChannelWider, OutChannelWider, BNWider
import numpy as np
OPS = {
    'none':
    lambda C, stride, affine: Zero(stride),
    'avg_pool_3x3':
    lambda C, stride, affine: AvgPoolBN(C, stride=stride),
    'max_pool_3x3':
    lambda C, stride, affine: MaxPoolBN(C, stride=stride),
    'skip_connect':
    lambda C, stride, affine: Identity()
    if stride == 1 else FactorizedReduce(C, C, affine=affine),
    'sep_conv_3x3':
    lambda C, stride, affine: SepConv(C, C, 3, stride, 1, affine=affine),
    'sep_conv_5x5':
    lambda C, stride, affine: SepConv(C, C, 5, stride, 2, affine=affine),
    'sep_conv_7x7':
    lambda C, stride, affine: SepConv(C, C, 7, stride, 3, affine=affine),
    'dil_conv_3x3':
    lambda C, stride, affine: DilConv(C, C, 3, stride, 2, 2, affine=affine),
    'dil_conv_5x5':
    lambda C, stride, affine: DilConv(C, C, 5, stride, 4, 2, affine=affine),
    'conv_7x1_1x7':
    lambda C, stride, affine: nn.Sequential(
        nn.ReLU(inplace=False),
        nn.Conv2d(C, C,
                  (1, 7), stride=(1, stride), padding=(0, 3), bias=False),
        nn.Conv2d(C, C,
                  (7, 1), stride=(stride, 1), padding=(3, 0), bias=False),
        nn.BatchNorm2d(C, affine=affine)),
}

class DilConvMixture(nn.Module):
    
  def __init__(self, op, kernel_size_list, kernel_max):
    super(DilConvMixture, self).__init__()
    self.op = op
    self.kernel_list = kernel_size_list
    self.kernel_max = kernel_max

  def _compute_weight_and_bias(self, weights, idx, conv_weight, conv_bias):
        alpha = weights[idx]

        kernel_size = self.kernel_list[idx]
        start = 0 + (self.kernel_max - kernel_size) // 2
        end = start + kernel_size
        weight_curr = self.op.op[1].weight[:, :, start:end, start:end]
        conv_weight += alpha * F.pad(weight_curr, (start, start, start, start), "constant", 0)

        if self.op.op[1].bias is not None:
            conv_bias += alpha * self.op.op[1].bias

        return conv_weight, conv_bias

  def forward(self, input, weights, use_argmax = False):
        x = input
        x = self.op.op[0](x)
        conv_weight = 0
        conv_bias = 0
        if use_argmax == True:
            argmax = np.array([w.item() for w in weights]).argmax()
            conv_weight, conv_bias = self._compute_weight_and_bias(
                weights=weights,
                idx=argmax,
                conv_weight=conv_weight,
                conv_bias=conv_bias
            )
        else:
            for i, _ in enumerate(weights):
                conv_weight, conv_bias = self._compute_weight_and_bias(
                    weights=weights,
                    idx=i,
                    conv_weight=conv_weight,
                    conv_bias=conv_bias
                )
        x = F.conv2d(x,
                weight=conv_weight,
                bias=conv_bias if self.op.op[1].bias is not None else None,
                stride=self.op.op[1].stride,
                padding=self.op.op[1].padding[0],
                dilation = self.op.op[1].dilation,
                groups = self.op.op[1].groups)  
        x = self.op.op[2](x)   
        x = self.op.op[3](x)
        return x

  def wider(self, new_C_in, new_C_out):
        conv1 = self.op.op[1]
        conv2 = self.op.op[2]
        bn = self.op.op[3]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn, _ = BNWider(bn, new_C_out, index=index)
        self.op.op[1] = conv1
        self.op.op[2] = conv2
        self.op.op[3] = bn


class SepConvMixture(nn.Module):
    
  def __init__(self, op, kernel_size_list, kernel_max):
    super(SepConvMixture, self).__init__()
    self.op = op
    self.kernel_list = kernel_size_list
    self.kernel_max = kernel_max

  def _compute_weight_and_bias(self, weights, idx, conv_weight, conv_bias, op_id):
    alpha = weights[idx]

    kernel_size = self.kernel_list[idx]
    start = 0 + (self.kernel_max - kernel_size) // 2
    end = start + kernel_size
    weight_curr = self.op.op[op_id].weight[:, :, start:end, start:end]
    conv_weight += alpha * F.pad(weight_curr, (start, start, start, start), "constant", 0)

    if self.op.op[1].bias is not None:
        conv_bias += alpha * self.op.op[op_id].bias

    return conv_weight, conv_bias

  def forward(self, input, weights , use_argmax=False ):
    x = input
    x = self.op.op[0](x)
    conv_weight = 0
    conv_bias = 0
    if use_argmax == True:
        argmax = np.array([w.item() for w in weights]).argmax()
        conv_weight, conv_bias = self._compute_weight_and_bias(
                weights=weights,
                idx=argmax,
                conv_weight=conv_weight,
                conv_bias=conv_bias,
                op_id=1
            )
    else:
        for i, _ in enumerate(weights):
            conv_weight, conv_bias = self._compute_weight_and_bias(
            weights=weights,
            idx=i,
            conv_weight=conv_weight,
            conv_bias=conv_bias,
            op_id=1
            )
    x = F.conv2d(x,
                weight=conv_weight,
                bias=conv_bias if self.op.op[1].bias is not None else None,
                stride=self.op.op[1].stride,
                padding=self.op.op[1].padding[0],
                dilation = self.op.op[1].dilation,
                groups = self.op.op[1].groups)  
    x = self.op.op[2](x)   
    x = self.op.op[3](x)
    x = self.op.op[4](x)
    conv_weight = 0
    conv_bias = 0
    if use_argmax == True:
        argmax = np.array([w.item() for w in weights]).argmax()
        conv_weight, conv_bias = self._compute_weight_and_bias(
                weights=weights,
                idx=argmax,
                conv_weight=conv_weight,
                conv_bias=conv_bias,
                op_id=5
            )
    else:
        for i, _ in enumerate(weights):
            conv_weight, conv_bias = self._compute_weight_and_bias(
            weights=weights,
            idx=i,
            conv_weight=conv_weight,
            conv_bias=conv_bias,
            op_id=5
            )
    x = F.conv2d(x,
                weight=conv_weight,
                bias=conv_bias if self.op.op[5].bias is not None else None,
                stride=self.op.op[5].stride,
                padding=self.op.op[5].padding[0],
                dilation = self.op.op[5].dilation,
                groups = self.op.op[5].groups) 
    x = self.op.op[6](x)
    x = self.op.op[7](x)
    return x

  def wider(self, new_C_in, new_C_out):
        conv1 = self.op.op[1]
        conv2 = self.op.op[2]
        conv3 = self.op.op[5]
        conv4 = self.op.op[6]
        bn1 = self.op.op[3]
        bn2 = self.op.op[7]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn1, _ = BNWider(bn1, new_C_out, index=index)

        conv3, index = OutChannelWider(conv3, new_C_out)
        conv3.groups = new_C_in
        conv4, _ = InChannelWider(conv4, new_C_in, index=index)
        conv4, index = OutChannelWider(conv4, new_C_out)
        bn2, _ = BNWider(bn2, new_C_out, index=index)
        self.op.op[1] = conv1
        self.op.op[2] = conv2
        self.op.op[5] = conv3
        self.op.op[6] = conv4
        self.op.op[3] = bn1
        self.op.op[7] = bn2
class AvgPoolBN(nn.Module):

    def __init__(self, C_out, stride):
        super(AvgPoolBN, self).__init__()
        self.op = nn.Sequential(
            nn.AvgPool2d(3, stride=stride, padding=1, count_include_pad=False),
            nn.BatchNorm2d(C_out, affine=False))

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        bn = self.op[1]
        bn, _ = BNWider(bn, new_C_out)
        self.op[1] = bn


class MaxPoolBN(nn.Module):

    def __init__(self, C_out, stride):
        super(MaxPoolBN, self).__init__()
        self.op = nn.Sequential(nn.MaxPool2d(3, stride=stride, padding=1),
                                nn.BatchNorm2d(C_out, affine=False))

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        bn = self.op[1]
        bn, _ = BNWider(bn, new_C_out)
        self.op[1] = bn


class ReLUConvBN(nn.Module):

    def __init__(self, C_in, C_out, kernel_size, stride, padding, affine=True):
        super(ReLUConvBN, self).__init__()
        self.op = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(C_in,
                      C_out,
                      kernel_size,
                      stride=stride,
                      padding=padding,
                      bias=False), nn.BatchNorm2d(C_out, affine=affine))

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        conv = self.op[1]
        bn = self.op[2]
        conv, _ = InChannelWider(conv, new_C_in)
        conv, index = OutChannelWider(conv, new_C_out)
        bn, _ = BNWider(bn, new_C_out, index=index)
        self.op[1] = conv
        self.op[2] = bn


class DilConv(nn.Module):

    def __init__(self,
                 C_in,
                 C_out,
                 kernel_size,
                 stride,
                 padding,
                 dilation,
                 affine=True):
        super(DilConv, self).__init__()
        self.op = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(C_in,
                      C_in,
                      kernel_size=kernel_size,
                      stride=stride,
                      padding=padding,
                      dilation=dilation,
                      groups=C_in,
                      bias=False),
            nn.Conv2d(C_in, C_out, kernel_size=1, padding=0, bias=False),
            nn.BatchNorm2d(C_out, affine=affine),
        )
        #print(self.op[1].weight.shape)

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        conv1 = self.op[1]
        conv2 = self.op[2]
        bn = self.op[3]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn, _ = BNWider(bn, new_C_out, index=index)
        self.op[1] = conv1
        self.op[2] = conv2
        self.op[3] = bn


class SubConv(nn.Module):

    def __init__(self, op, kernel_size):
        super(SubConv, self).__init__()
        #print(op.weight.shape)
        self.kernel_size = kernel_size
        self.op = op

    def forward(self, x):
        #print(self.weight_sub.shape)
        #print(x.device)
        #print(self.weight_sub.device)
        #print(self.op.stride)
        if self.op.padding[0] == 2:
            x = F.conv2d(x,
                         weight=self.op.weight[:, :, 1:(1 + self.kernel_size),
                                               1:(1 + self.kernel_size)],
                         bias=self.op.bias,
                         stride=self.op.stride,
                         padding=self.op.padding[0] - 1,
                         groups=self.op.groups)
        else:
            x = F.conv2d(x,
                         weight=self.op.weight[:, :, 1:(1 + self.kernel_size),
                                               1:(1 + self.kernel_size)],
                         bias=self.op.bias,
                         stride=self.op.stride,
                         padding=self.op.padding[0] - 2,
                         dilation=self.op.dilation,
                         groups=self.op.groups)
        return x


class DilConvSubSample(nn.Module):

    def __init__(self, layer, kernel_size):
        super(DilConvSubSample, self).__init__()
        self.op = nn.Sequential(layer.op[0], SubConv(layer.op[1], kernel_size),
                                layer.op[2], layer.op[3])

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        conv1 = self.op[1]
        conv2 = self.op[2]
        bn = self.op[3]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn, _ = BNWider(bn, new_C_out, index=index)
        self.op[1] = conv1
        self.op[2] = conv2
        self.op[3] = bn


class SepConvSubSample(nn.Module):

    def __init__(self, layer, kernel_size):
        super(SepConvSubSample, self).__init__()
        self.op = nn.Sequential(
            layer.op[0],
            SubConv(layer.op[1], kernel_size),
            layer.op[2],
            layer.op[3],
            layer.op[4],
            SubConv(layer.op[5], kernel_size),
            layer.op[6],
            layer.op[7],
        )

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        conv1 = self.op[1]
        conv2 = self.op[2]
        conv3 = self.op[5]
        conv4 = self.op[6]
        bn1 = self.op[3]
        bn2 = self.op[7]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn1, _ = BNWider(bn1, new_C_out, index=index)

        conv3, index = OutChannelWider(conv3, new_C_out)
        conv3.groups = new_C_in
        conv4, _ = InChannelWider(conv4, new_C_in, index=index)
        conv4, index = OutChannelWider(conv4, new_C_out)
        bn2, _ = BNWider(bn2, new_C_out, index=index)
        self.op[1] = conv1
        self.op[2] = conv2
        self.op[5] = conv3
        self.op[6] = conv4
        self.op[3] = bn1
        self.op[7] = bn2


class SepConv(nn.Module):

    def __init__(self, C_in, C_out, kernel_size, stride, padding, affine=True):
        super(SepConv, self).__init__()
        self.op = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(C_in,
                      C_in,
                      kernel_size=kernel_size,
                      stride=stride,
                      padding=padding,
                      groups=C_in,
                      bias=False),
            nn.Conv2d(C_in, C_in, kernel_size=1, padding=0, bias=False),
            nn.BatchNorm2d(C_in, affine=affine),
            nn.ReLU(inplace=False),
            nn.Conv2d(C_in,
                      C_in,
                      kernel_size=kernel_size,
                      stride=1,
                      padding=padding,
                      groups=C_in,
                      bias=False),
            nn.Conv2d(C_in, C_out, kernel_size=1, padding=0, bias=False),
            nn.BatchNorm2d(C_out, affine=affine),
        )

    def forward(self, x):
        return self.op(x)

    def wider(self, new_C_in, new_C_out):
        conv1 = self.op[1]
        conv2 = self.op[2]
        conv3 = self.op[5]
        conv4 = self.op[6]
        bn1 = self.op[3]
        bn2 = self.op[7]
        conv1, index = OutChannelWider(conv1, new_C_out)
        conv1.groups = new_C_in
        conv2, _ = InChannelWider(conv2, new_C_in, index=index)
        conv2, index = OutChannelWider(conv2, new_C_out)
        bn1, _ = BNWider(bn1, new_C_out, index=index)

        conv3, index = OutChannelWider(conv3, new_C_out)
        conv3.groups = new_C_in
        conv4, _ = InChannelWider(conv4, new_C_in, index=index)
        conv4, index = OutChannelWider(conv4, new_C_out)
        bn2, _ = BNWider(bn2, new_C_out, index=index)
        self.op[1] = conv1
        self.op[2] = conv2
        self.op[5] = conv3
        self.op[6] = conv4
        self.op[3] = bn1
        self.op[7] = bn2


class Identity(nn.Module):

    def __init__(self):
        super(Identity, self).__init__()

    def forward(self, x):
        return x

    def wider(self, new_C_in, new_C_out):
        pass


class Zero(nn.Module):

    def __init__(self, stride):
        super(Zero, self).__init__()
        self.stride = stride

    def forward(self, x):
        if self.stride == 1:
            return x.mul(0.)
        return x[:, :, ::self.stride, ::self.stride].mul(0.)

    def wider(self, new_C_in, new_C_out):
        pass


class FactorizedReduce(nn.Module):

    def __init__(self, C_in, C_out, affine=True):
        super(FactorizedReduce, self).__init__()
        assert C_out % 2 == 0
        self.relu = nn.ReLU(inplace=False)
        self.conv_1 = nn.Conv2d(C_in,
                                C_out // 2,
                                1,
                                stride=2,
                                padding=0,
                                bias=False)
        self.conv_2 = nn.Conv2d(C_in,
                                C_out // 2,
                                1,
                                stride=2,
                                padding=0,
                                bias=False)
        self.bn = nn.BatchNorm2d(C_out, affine=affine)

    def forward(self, x):
        x = self.relu(x)
        out = torch.cat([self.conv_1(x), self.conv_2(x[:, :, 1:, 1:])], dim=1)
        out = self.bn(out)
        return out

    def wider(self, new_C_in, new_C_out):
        self.conv_1, _ = InChannelWider(self.conv_1, new_C_in)
        self.conv_1, index1 = OutChannelWider(self.conv_1, new_C_out // 2)
        self.conv_2, _ = InChannelWider(self.conv_2, new_C_in)
        self.conv_2, index2 = OutChannelWider(self.conv_2, new_C_out // 2)
        self.bn, _ = BNWider(self.bn,
                             new_C_out,
                             index=torch.cat([index1, index2]))
