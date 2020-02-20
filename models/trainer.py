# Copyright (c) 2019, NVIDIA Corporation. All rights reserved.
#
# This work is made available
# under the Nvidia Source Code License (1-way Commercial).
# To view a copy of this license, visit
# https://nvlabs.github.io/few-shot-vid2vid/License.txt
import os
import numpy as np
import time
from collections import OrderedDict
import fractions
from subprocess import call
def lcm(a,b): return abs(a * b)/fractions.gcd(a,b) if a and b else 0

import util.util as util
from util.visualizer import Visualizer
from models.models import save_models, update_models
from util.distributed import master_only, is_master
from util.distributed import master_only_print as print

import pdb
class Trainer():    
    def __init__(self, opt, data_loader):
        iter_path = os.path.join(opt.checkpoints_dir, opt.name, 'iter.txt')
        start_epoch, epoch_iter = 1, 0
        ### if continue training, recover previous states
        if opt.continue_train:        
            if os.path.exists(iter_path):
                start_epoch, epoch_iter = np.loadtxt(iter_path , delimiter=',', dtype=int)        
            print('Resuming from epoch %d at iteration %d' % (start_epoch, epoch_iter))                                                      
                
        print_freq = lcm(opt.print_freq, opt.batchSize)
        total_steps = (start_epoch-1) * len(data_loader) + epoch_iter
        total_steps = total_steps // print_freq * print_freq  

        self.opt = opt
        self.epoch_iter, self.print_freq, self.total_steps, self.iter_path = epoch_iter, print_freq, total_steps, iter_path
        self.start_epoch, self.epoch_iter = start_epoch, epoch_iter
        self.dataset_size = len(data_loader)
        self.visualizer = Visualizer(opt)        

    def start_of_iter(self):
        if self.total_steps % self.print_freq == 0:
            self.iter_start_time = time.time()
        self.total_steps += self.opt.batchSize
        self.epoch_iter += self.opt.batchSize 
        self.save = self.total_steps % self.opt.display_freq == 0            

    def end_of_iter(self, loss_dicts, output_list, model):
        opt = self.opt
        epoch, epoch_iter, print_freq, total_steps = self.epoch, self.epoch_iter, self.print_freq, self.total_steps
        ############## Display results and errors ##########
        ### print out errors        
        if is_master() and total_steps % print_freq == 0:
            t = (time.time() - self.iter_start_time) / print_freq            
            errors = {k: v.data.item() if not isinstance(v, int) else v for k, v in loss_dicts.items()}
            self.visualizer.print_current_errors(epoch, epoch_iter, errors, t)
            self.visualizer.plot_current_errors(errors, total_steps)

        # debug
        # visuals = save_all_tensors(opt, output_list, model)
        # self.visualizer.display_current_results(visuals, epoch, total_steps)

        ### display output images        
        if is_master() and self.save:
            visuals = save_all_tensors(opt, output_list, model)
            self.visualizer.display_current_results(visuals, epoch, total_steps)

        if is_master() and opt.print_mem:
            call(["nvidia-smi", "--format=csv", "--query-gpu=memory.used,memory.free"]) 

        ### save latest model
        save_models(opt, epoch, epoch_iter, total_steps, self.visualizer, self.iter_path, model)
        if epoch_iter > self.dataset_size - opt.batchSize:            
            return True
        return False

    def start_of_epoch(self, epoch, model, data_loader):
        self.epoch = epoch
        self.epoch_start_time = time.time()
        if self.opt.distributed:
            data_loader.dataloader.sampler.set_epoch(epoch)
        # update model params
        update_models(self.opt, epoch, model, data_loader) 

    def end_of_epoch(self, model):        
        opt = self.opt
        iter_end_time = time.time()
        self.visualizer.vis_print(opt, 'End of epoch %d / %d \t Time Taken: %d sec' %
              (self.epoch, opt.niter + opt.niter_decay, time.time() - self.epoch_start_time))

        ### save model for this epoch
        save_models(opt, self.epoch, self.epoch_iter, self.total_steps, self.visualizer, self.iter_path, model, end_of_epoch=True)        
        self.epoch_iter = 0        
    
def save_all_tensors(opt, output_list, model):
    fake_image, fake_raw_image, img_ani, warped_image, flow, weight, atn_score, \
        target_label, target_image, cropped_images, flow_gt, conf_gt, \
        ref_label, ref_image, \
        warping_ref_lmark, warping_ref, ani_lmark, ani_image, cropped_lmarks = output_list

    visual_list = []
    for i in range(opt.n_shot):
        visual_list += [('ref_img_{}'.format(i), util.tensor2im(ref_image[:, i:i+1]))]
    visual_list += [('warping_ref_lmark', util.tensor2im(warping_ref_lmark)),
                    ('warping_ref_img', util.tensor2im(warping_ref)),
                    ('target_label', util.visualize_label(opt, target_label, model)),
                    ('target_image', util.tensor2im(target_image)),
                    ('synthesized_image', util.tensor2im(fake_image)),
                    ('ani_syn_image', util.tensor2im(img_ani)),
                    ('ref_warped_images', util.tensor2im(warped_image[0][-1], tile=True)),
                    ('ref_weights', util.tensor2im(weight[0][-1], normalize=False, tile=True)),
                    ('prev_warped_images', util.tensor2im(warped_image[1][-1], tile=True) if warped_image[1] is not None else None),
                    ('prev_weights', util.tensor2im(weight[1][-1], normalize=False, tile=True) if weight[1] is not None else None),
                    ('raw_image', util.tensor2im(fake_raw_image)),
                    ('ani_warped_images', util.tensor2im(warped_image[2][-1], tile=True) if warped_image[2] is not None else None),
                    ('ani_weights', util.tensor2im(weight[2][-1], normalize=False, tile=True) if weight[2] is not None else None),
                    ('ani_flow', util.tensor2flow(flow[2][-1], tile=True) if flow[2] is not None else None),
                    ('ref_flow', util.tensor2flow(flow[0][-1], tile=True)),
                    ('ani_image', util.tensor2im(ani_image)),
                    ('ani_lmark', util.tensor2im(ani_lmark)),
                    ('cropped_image', util.tensor2im(cropped_images)),
                    ('cropped_lmark', util.tensor2im(cropped_lmarks)),
                    ('flow_ref_gt', util.tensor2flow(flow_gt[0][-1][-1], tile=True) if flow[2] is not None else None),
                    ('flow_ani_gt', util.tensor2flow(flow_gt[2][-1][-1], tile=True) if flow[2] is not None else None),
                    ]
    visuals = OrderedDict(visual_list)
    return visuals