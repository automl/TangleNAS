import torch.nn as nn
import torch.nn.functional as F
import torch
import torchvision
import torchvision.transforms as transforms
import torch.optim as optim
import numpy as np
import pickle
import argparse

import wandb
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from datasets.data import CIFAR10Data
import os, time
class ConvNet(nn.Module):
    
    def __init__(self):
        super(ConvNet,self).__init__()
        
        self.conv1 = nn.Conv2d(in_channels=3,out_channels=32,kernel_size=(7,7),stride=1, padding=3)
        self.conv2 = nn.Conv2d(in_channels=32,out_channels=64,kernel_size=(7,7),padding=3,stride=1)
        self.conv3 = nn.Conv2d(in_channels=64,out_channels=128,kernel_size=(7,7),padding=3,stride=1)
        self.conv4 = nn.Conv2d(in_channels=128,out_channels=256,kernel_size=(7,7),padding=3,stride=1)
        self.conv5 = nn.Conv2d(in_channels=256,out_channels=256,kernel_size=(7,7),stride=1, padding=2)

        self.fc1 = nn.Linear(in_features=6*6*256,out_features=256)
        self.fc2 = nn.Linear(in_features=256,out_features=128)
        self.fc3 = nn.Linear(in_features=128,out_features=64)
        self.fc4 = nn.Linear(in_features=64,out_features=10)
        
        self.max_pool = nn.MaxPool2d(kernel_size=(2,2),stride=2)
        self.dropout = nn.Dropout2d(p=0.5)
        
    def random_sample_channel(self):
        choices = []
        choices.append(np.random.choice([8,16,32]))
        choices.append(np.random.choice([16,32,64]))
        choices.append(np.random.choice([32,64,128]))
        choices.append(np.random.choice([64,128,256]))
        return choices
    
    def random_sample_kernel(self):
        choices = []
        choices.append(np.random.choice([3,5,7]))
        choices.append(np.random.choice([3,5,7]))
        choices.append(np.random.choice([3,5,7]))
        choices.append(np.random.choice([3,5,7]))
        return choices
    
    def sample_all_choices(self):
        arch_choices = []
        for c4 in [64,128,256]:
            for k4 in [3,5,7]:
                for c3 in [32,64,128]:
                    for k3 in [3,5,7]:
                        for c2 in [16,32,64]:
                            for k2 in [3,5,7]:
                                for c1 in [8,16,32]:
                                    for k1 in [3,5,7]:
                                        arch_choices.append([[c1,c2,c3,c4],[k1,k2,k3,k4]])
        return arch_choices
    
    def forward(self,x):
        choices_channel  = self.random_sample_channel()
        choices_kernel = self.random_sample_kernel()
        if choices_kernel[0] == 7:
            x = torch.nn.functional.conv2d(x, self.conv1.weight[:choices_channel[0],:3,:,:], self.conv1.bias[:choices_channel[0]], padding=3)
        elif choices_kernel[0] == 5:
            x = torch.nn.functional.conv2d(x, self.conv1.weight[:choices_channel[0],:3,1:6,1:6], self.conv1.bias[:choices_channel[0]], padding=2)
        elif choices_kernel[0] == 3:
            x = torch.nn.functional.conv2d(x, self.conv1.weight[:choices_channel[0],:3,2:5,2:5], self.conv1.bias[:choices_channel[0]], padding=1)
        #print(x.shape)
        x = F.relu(x)
        if choices_kernel[1] == 7:
            x = torch.nn.functional.conv2d(x, self.conv2.weight[:choices_channel[1],:choices_channel[0],:,:], self.conv2.bias[:choices_channel[1]], padding=3)
        elif choices_kernel[1] == 5:
            x = torch.nn.functional.conv2d(x, self.conv2.weight[:choices_channel[1],:choices_channel[0],1:6,1:6], self.conv2.bias[:choices_channel[1]], padding=2)
        elif choices_kernel[1] == 3:
            x = torch.nn.functional.conv2d(x, self.conv2.weight[:choices_channel[1],:choices_channel[0],2:5,2:5], self.conv2.bias[:choices_channel[1]], padding=1)
        #print(x.shape)
        x = F.relu(x)
        x = self.max_pool(x)
        if choices_kernel[2] == 7:
            x = torch.nn.functional.conv2d(x, self.conv3.weight[:choices_channel[2],:choices_channel[1],:,:], self.conv3.bias[:choices_channel[2]], padding=3)
        elif choices_kernel[2] == 5:
            x = torch.nn.functional.conv2d(x, self.conv3.weight[:choices_channel[2],:choices_channel[1],1:6,1:6], self.conv3.bias[:choices_channel[2]], padding=2)
        elif choices_kernel[2] == 3:
            x = torch.nn.functional.conv2d(x, self.conv3.weight[:choices_channel[2],:choices_channel[1],2:5,2:5], self.conv3.bias[:choices_channel[2]], padding=1)
        #print(x.shape)
        x = F.relu(x)
        x = self.dropout(x)
       
        #print(x.shape)
        x = F.relu(x)
        x = self.max_pool(x)
        if choices_kernel[3] == 7:
            x = torch.nn.functional.conv2d(x, self.conv4.weight[:choices_channel[3],:choices_channel[2],:,:], self.conv4.bias[:choices_channel[3]], padding=3)
        elif choices_kernel[3] == 5:
            x = torch.nn.functional.conv2d(x, self.conv4.weight[:choices_channel[3],:choices_channel[2],1:6,1:6], self.conv4.bias[:choices_channel[3]], padding=2)
        elif choices_kernel[3] == 3:
            x = torch.nn.functional.conv2d(x, self.conv4.weight[:choices_channel[3],:choices_channel[2],2:5,2:5], self.conv4.bias[:choices_channel[3]], padding=1)
        #print(x.shape)
        x = F.relu(x)
        x = torch.nn.functional.conv2d(x, self.conv5.weight[:,:choices_channel[3],:,:], self.conv5.bias, padding=2)
        #print(x.shape)

        x = self.dropout(x)
        x = x.view(-1,6*6*256)
        x = self.fc1(x)
        x = F.relu(x)
        x = self.fc2(x)
        x = F.relu(x)
        x = self.fc3(x)
        x = F.relu(x)
        logits = self.fc4(x)
        return logits
    
    def configure_optimizers(self):
        optimizer = optim.Adam(self.parameters(),lr=3e-4,betas=(0.9,0.995),weight_decay=5e-4)
        return optimizer
    
def train_spos(trainloader, valid_loader, testloader, train_portion, args):
    net = ConvNet().cuda()
    criterion = nn.CrossEntropyLoss()
    optimizer = net.configure_optimizers()
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=2000, eta_min=0.0001)
    root_dir = "conv_macro_output_search/"
    if not os.path.exists(root_dir):
        os.mkdir(root_dir)
    time_str = time.strftime("%Y%m%d-%H%M%S")
    current_dir = root_dir+"/"+str(args.optimizer)+"_"+str(args.train_portion)+"_"+str(args.seed)+"_"+time_str
    wandb_run_name = "conv_macro_train_spos"+"_"+str(args.optimizer)+"_"+str(args.seed)+"_"+str(args.train_portion)+"_"+time_str
    os.mkdir(current_dir)
    wandb.init(project="conv_macro_spos", name=wandb_run_name, config=args)
    for epoch in range(2000):
        running_loss = 0.0
        for i, data in enumerate(trainloader, 0):
            # get the inputs; data is a list of [inputs, labels]
            inputs, labels = data
            inputs = inputs.cuda()
            labels = labels.cuda()
            # zero the parameter gradients
            optimizer.zero_grad()
            #forward + backward + optimize
            outputs = net(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            #scheduler.step()
            # print statistics
            running_loss += loss.item()
            if i % 100 == 0:    # print every 2000 mini-batches
                print(f'[{epoch + 1}, {i + 1:5d}] loss: {running_loss / 100:.3f}')
                running_loss = 0.0
                
            if i%500 == 0:
                test_acc = test_arch(testloader, net)
                wandb.log({"test_acc": test_acc})
                valid_acc = test_arch(valid_loader, net)
                wandb.log({"valid_acc": valid_acc})
                wandb.log({"loss": loss})
                PATH = current_dir+"/"+'cifar_net_we_spos_{epoch}_{i}_{train_portion}.pth'.format(epoch=epoch, i=i, train_portion=train_portion)
                torch.save(net.state_dict(), PATH)
        scheduler.step()

def test_arch(testloader, net):
    correct = 0
    total = 0
    # since we're not training, we don't need to calculate the gradients for our outputs
    with torch.no_grad():
        for data in testloader:
            images, labels = data
            images = images.cuda()
            labels = labels.cuda()
            # calculate outputs by running images through the network
            outputs = net(images)
            # the class with the highest energy is what we choose as prediction
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    print('Accuracy of the network on the 10000 test images: %d %%' % (100 * correct / total))
    return 100 * correct / total

# write main method
if __name__ == '__main__':
    # get the data
    parser = argparse.ArgumentParser("cifar-channel-kernel")
    parser.add_argument('--benchmark_file_name', type=str, default='benchmark_dictionary_1.pkl', help='benchmark_file_name')
    parser.add_argument('--start_index', type=int, default=0, help='start_index')
    parser.add_argument('--end_index', type=int, default=100, help='end_index')
    parser.add_argument('--train_portion', type=float, default=0.8, help='train_portion')
    parser.add_argument('--seed', type=int, default=0, help='seed')
    parser.add_argument('--optimizer', type=str, default='spos', help='one shot optimizer')
    args = parser.parse_args()
    cifar_loader = CIFAR10Data("data/",cutout=0,train_portion=args.train_portion)
    train_queue, valid_queue, test_queue = cifar_loader.get_dataloaders(batch_size=64)

    train_spos(train_queue, valid_queue, test_queue, train_portion=args.train_portion,args=args)