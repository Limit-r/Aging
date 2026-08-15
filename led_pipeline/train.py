#-------------------------------------#
#       对数据集进行训练
#-------------------------------------#
import datetime
import os
import sys
import json
import torch
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from functools import partial

import numpy as np

from model.YOLOV8 import YoloBody

from model.yolo_training import (Loss, ModelEMA, get_lr_scheduler,
                                set_optimizer_lr, weights_init)
from utils.callbacks import EvalCallback, LossHistory
from utils.dataloader import YoloDataset, yolo_dataset_collate
from utils.utils import (download_weights, get_classes, seed_everything,
                         show_config, worker_init_fn)
from utils.utils_fit import fit_one_epoch, print_detailed_metrics

from config import get_config


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def train(cfg):
    """
    根据配置字典执行训练流程
    cfg: dict，包含所有训练参数
    """
    # --- 从配置中提取参数 ---
    Cuda            = cfg['Cuda']
    seed            = cfg['seed']
    distributed     = cfg['distributed']
    sync_bn         = cfg['sync_bn']
    fp16            = cfg['fp16']
    classes_path    = cfg['classes_path']
    model_path      = cfg['model_path']
    input_shape     = cfg['input_shape']
    phi             = cfg['phi']
    pretrained      = cfg['pretrained']
    mosaic          = cfg['mosaic']
    mosaic_prob     = cfg['mosaic_prob']
    mixup           = cfg['mixup']
    mixup_prob      = cfg['mixup_prob']
    special_aug_ratio = cfg['special_aug_ratio']
    label_smoothing = cfg['label_smoothing']
    Init_Epoch      = cfg['Init_Epoch']
    Freeze_Epoch    = cfg['Freeze_Epoch']
    Freeze_batch_size = cfg['Freeze_batch_size']
    UnFreeze_Epoch  = cfg['UnFreeze_Epoch']
    Unfreeze_batch_size = cfg['Unfreeze_batch_size']
    Freeze_Train    = cfg['Freeze_Train']
    Init_lr         = cfg['Init_lr']
    Min_lr          = cfg['Min_lr']
    optimizer_type  = cfg['optimizer_type']
    momentum        = cfg['momentum']
    weight_decay    = cfg['weight_decay']
    lr_decay_type   = cfg['lr_decay_type']
    save_period     = cfg['save_period']
    save_dir        = cfg['save_dir']
    eval_flag       = cfg['eval_flag']
    eval_period     = cfg['eval_period']
    num_workers     = cfg['num_workers']
    train_annotation_path = cfg['train_annotation_path']
    val_annotation_path = cfg['val_annotation_path']
    gradient_clip_norm = cfg['gradient_clip_norm']
    min_recall_threshold = cfg['min_recall_threshold']
    min_f1_threshold = cfg['min_f1_threshold']
    export_deploy_model = cfg['export_deploy_model']
    early_stop_enabled  = cfg.get('early_stop_enabled', False)
    early_stop_patience = cfg.get('early_stop_patience', 20)
    early_stop_metric   = cfg.get('early_stop_metric', 'val_loss')
    epoch_offset        = cfg.get('epoch_offset', 0)

    #==================================================#
    #                开始执行训练流程
    #==================================================#

    seed_everything(seed)

    #------------------------------------------------------#
    #   设置用到的显卡
    #------------------------------------------------------#
    ngpus_per_node  = torch.cuda.device_count()
    if distributed:
        dist.init_process_group(backend="nccl")
        local_rank  = int(os.environ["LOCAL_RANK"])
        rank        = int(os.environ["RANK"])
        device      = torch.device("cuda", local_rank)
        if local_rank == 0:
            print(f"[{os.getpid()}] (rank = {rank}, local_rank = {local_rank}) training...")
            print("Gpu Device Count : ", ngpus_per_node)
    else:
        device          = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        local_rank      = 0
        rank            = 0

    #------------------------------------------------------#
    #   获取classes和anchor
    #------------------------------------------------------#
    class_names, num_classes = get_classes(classes_path)

    #----------------------------------------------------#
    #   下载预训练权重
    #----------------------------------------------------#
    if pretrained:
        if distributed:
            if local_rank == 0:
                download_weights(phi)  
            dist.barrier()
        else:
            download_weights(phi)
            
    #------------------------------------------------------#
    #   创建yolo模型
    #------------------------------------------------------#
    model = YoloBody(input_shape, num_classes, phi, pretrained=pretrained)

    if model_path != '':
        if local_rank == 0:
            print('Load weights {}.'.format(model_path))
        
        model_dict      = model.state_dict()
        pretrained_dict = torch.load(model_path, map_location=device, weights_only=False)
        # 兼容处理: 预训练权重 key 可能缺少 'backbone.' 前缀（如 stem.conv.weight），
        # 而模型 key 为 backbone.stem.conv.weight，此处自动补全前缀以正确加载主干网络。
        if isinstance(pretrained_dict, dict):
            fixed_dict = {}
            for k, v in pretrained_dict.items():
                if k not in model_dict.keys() and ('backbone.' + k) in model_dict.keys():
                    k = 'backbone.' + k
                fixed_dict[k] = v
            pretrained_dict = fixed_dict
        load_key, no_load_key, temp_dict = [], [], {}
        for k, v in pretrained_dict.items():
            if k in model_dict.keys() and np.shape(model_dict[k]) == np.shape(v):
                temp_dict[k] = v
                load_key.append(k)
            else:
                no_load_key.append(k)
        model_dict.update(temp_dict)
        model.load_state_dict(model_dict)

        if local_rank == 0:
            print("\nSuccessful Load Key:", str(load_key)[:500], "……\nSuccessful Load Key Num:", len(load_key))
            print("\nFail To Load Key:", str(no_load_key)[:500], "……\nFail To Load Key num:", len(no_load_key))
            print("\n\033[1;33;44m温馨提示，head部分没有载入是正常现象，Backbone部分没有载入是错误的。\033[0m")

    #----------------------#
    #   获得损失函数
    #----------------------#
    yolo_loss = Loss(model)
    #----------------------#
    #   记录Loss
    #----------------------#
    if local_rank == 0:
        time_str        = datetime.datetime.strftime(datetime.datetime.now(),'%Y_%m_%d_%H_%M_%S')
        log_dir         = os.path.join(save_dir, "loss_" + str(time_str))
        loss_history    = LossHistory(log_dir, model, input_shape=input_shape)
    else:
        loss_history    = None
        
    #------------------------------------------------------------------#
    #   torch 1.2不支持amp，建议使用torch 1.7.1及以上正确使用fp16
    #------------------------------------------------------------------#
    if fp16:
        from torch.cuda.amp import GradScaler
        scaler = GradScaler()
    else:
        scaler = None

    model_train = model.train()

    #----------------------------#
    #   多卡同步Bn
    #----------------------------#
    if sync_bn and ngpus_per_node > 1 and distributed:
        model_train = torch.nn.SyncBatchNorm.convert_sync_batchnorm(model_train)
    elif sync_bn:
        print("Sync_bn is not support in one gpu or not distributed.")

    if Cuda:
        if distributed:
            model_train = model_train.cuda(local_rank)
            model_train = torch.nn.parallel.DistributedDataParallel(model_train, device_ids=[local_rank], find_unused_parameters=True)
        else:
            model_train = torch.nn.DataParallel(model)
            cudnn.benchmark = True
            cudnn.deterministic = False
            model_train = model_train.cuda()
            
    #----------------------------#
    #   权值平滑
    #----------------------------#
    ema = ModelEMA(model_train)
    
    #---------------------------#
    #   读取数据集对应的txt
    #---------------------------#
    with open(train_annotation_path, encoding='utf-8') as f:
        train_lines = f.readlines()
    with open(val_annotation_path, encoding='utf-8') as f:
        val_lines   = f.readlines()
    num_train   = len(train_lines)
    num_val     = len(val_lines)

    if local_rank == 0:
        show_config(
            classes_path=classes_path, model_path=model_path, input_shape=input_shape,
            Init_Epoch=Init_Epoch, Freeze_Epoch=Freeze_Epoch, UnFreeze_Epoch=UnFreeze_Epoch,
            Freeze_batch_size=Freeze_batch_size, Unfreeze_batch_size=Unfreeze_batch_size,
            Freeze_Train=Freeze_Train,
            Init_lr=Init_lr, Min_lr=Min_lr, optimizer_type=optimizer_type, momentum=momentum,
            lr_decay_type=lr_decay_type,
            save_period=save_period, save_dir=save_dir, num_workers=num_workers,
            num_train=num_train, num_val=num_val
        )

        wanted_step = 5e4 if optimizer_type == "sgd" else 1.5e4
        total_step = num_train // Unfreeze_batch_size * UnFreeze_Epoch
        if total_step <= wanted_step:
            if num_train // Unfreeze_batch_size == 0:
                raise ValueError('数据集过小，无法进行训练，请扩充数据集。')
            wanted_epoch = wanted_step // (num_train // Unfreeze_batch_size) + 1
            print("\n\033[1;33;44m[Warning] 使用%s优化器时，建议将训练总步长设置到%d以上。\033[0m" % (optimizer_type, wanted_step))
            print("\033[1;33;44m[Warning] 本次运行的总训练数据量为%d，Unfreeze_batch_size为%d，共训练%d个Epoch，计算出总训练步长为%d。\033[0m" % (num_train, Unfreeze_batch_size, UnFreeze_Epoch, total_step))
            print("\033[1;33;44m[Warning] 由于总训练步长为%d，小于建议总步长%d，建议设置总世代为%d。\033[0m" % (total_step, wanted_step, wanted_epoch))

    #------------------------------------------------------#
    #   开始训练
    #------------------------------------------------------#
    if True:
        UnFreeze_flag = False
        batch_size = Freeze_batch_size if Freeze_Train else Unfreeze_batch_size

        nbs = 64
        lr_limit_max = 1e-3 if optimizer_type == 'adam' else 5e-2
        lr_limit_min = 3e-4 if optimizer_type == 'adam' else 5e-4
        Init_lr_fit = min(max(batch_size / nbs * Init_lr, lr_limit_min), lr_limit_max)
        Min_lr_fit = min(max(batch_size / nbs * Min_lr, lr_limit_min * 1e-2), lr_limit_max * 1e-2)

        pg0, pg1, pg2 = [], [], []
        for k, v in model.named_modules():
            if hasattr(v, "bias") and isinstance(v.bias, nn.Parameter):
                pg2.append(v.bias)
            if isinstance(v, nn.BatchNorm2d) or "bn" in k:
                pg0.append(v.weight)
            elif hasattr(v, "weight") and isinstance(v.weight, nn.Parameter):
                pg1.append(v.weight)
        optimizer = {
            'adam': optim.Adam(pg0, Init_lr_fit, betas=(momentum, 0.999)),
            'sgd': optim.SGD(pg0, Init_lr_fit, momentum=momentum, nesterov=True)
        }[optimizer_type]
        optimizer.add_param_group({"params": pg1, "weight_decay": weight_decay})
        optimizer.add_param_group({"params": pg2})

        lr_scheduler_func = get_lr_scheduler(lr_decay_type, Init_lr_fit, Min_lr_fit, UnFreeze_Epoch)
        
        epoch_step = num_train // batch_size
        epoch_step_val = num_val // batch_size
        
        if epoch_step == 0 or epoch_step_val == 0:
            raise ValueError("数据集过小，无法继续进行训练，请扩充数据集。")

        if ema:
            ema.updates = epoch_step * Init_Epoch

        train_dataset = YoloDataset(train_lines, input_shape, num_classes, epoch_length=UnFreeze_Epoch,
                                    mosaic=mosaic, mixup=mixup, mosaic_prob=mosaic_prob, mixup_prob=mixup_prob,
                                    train=True, special_aug_ratio=special_aug_ratio)
        val_dataset = YoloDataset(val_lines, input_shape, num_classes, epoch_length=UnFreeze_Epoch,
                                  mosaic=False, mixup=False, mosaic_prob=0, mixup_prob=0,
                                  train=False, special_aug_ratio=0)
        
        if distributed:
            train_sampler = torch.utils.data.distributed.DistributedSampler(train_dataset, shuffle=True)
            val_sampler = torch.utils.data.distributed.DistributedSampler(val_dataset, shuffle=False)
            batch_size = batch_size // ngpus_per_node
            shuffle = False
        else:
            train_sampler = None
            val_sampler = None
            shuffle = True

        gen = DataLoader(train_dataset, shuffle=shuffle, batch_size=batch_size, num_workers=num_workers,
                         pin_memory=True, drop_last=True, collate_fn=yolo_dataset_collate,
                         sampler=train_sampler,
                         worker_init_fn=partial(worker_init_fn, rank=rank, seed=seed),
                         persistent_workers=True if num_workers > 0 else False,
                         prefetch_factor=3 if num_workers > 0 else None)
        gen_val = DataLoader(val_dataset, shuffle=shuffle, batch_size=batch_size, num_workers=num_workers,
                             pin_memory=True, drop_last=True, collate_fn=yolo_dataset_collate,
                             sampler=val_sampler,
                             worker_init_fn=partial(worker_init_fn, rank=rank, seed=seed),
                             persistent_workers=True if num_workers > 0 else False,
                             prefetch_factor=3 if num_workers > 0 else None)

        if local_rank == 0:
            eval_callback = EvalCallback(model, input_shape, class_names, num_classes, val_lines, log_dir, Cuda,
                                         eval_flag=eval_flag, period=eval_period, verbose=False)
        else:
            eval_callback = None

        # 初始化最佳指标
        best_map = 0.0
        best_precision = 0.0
        best_recall = 0.0
        best_f1 = 0.0

        # 早停状态
        best_val_loss = float('inf')
        no_improve_epochs = 0
        
        if model_path != '' and os.path.exists(model_path):
            try:
                checkpoint = torch.load(model_path, map_location=device)
                if 'best_map' in checkpoint:
                    best_map = checkpoint['best_map']
                    print(f"Loaded previous best mAP: {best_map:.4f}")
                if 'best_precision' in checkpoint:
                    best_precision = checkpoint['best_precision']
                    print(f"Loaded previous best precision: {best_precision:.4f}")
                if 'best_recall' in checkpoint:
                    best_recall = checkpoint['best_recall']
                    print(f"Loaded previous best recall: {best_recall:.4f}")
                if 'best_f1' in checkpoint:
                    best_f1 = checkpoint['best_f1']
                    print(f"Loaded previous best F1-score: {best_f1:.4f}")
                if 'best_val_loss' in checkpoint:
                    best_val_loss = checkpoint['best_val_loss']
                    print(f"Loaded previous best val_loss: {best_val_loss:.4f}")
                if 'no_improve_epochs' in checkpoint:
                    no_improve_epochs = checkpoint['no_improve_epochs']
            except Exception as e:
                if "weights_only" in str(e):
                    try:
                        checkpoint = torch.load(model_path, map_location=device, weights_only=False)
                        if 'best_map' in checkpoint:
                            best_map = checkpoint['best_map']
                            print(f"Loaded previous best mAP: {best_map:.4f}")
                        if 'best_precision' in checkpoint:
                            best_precision = checkpoint['best_precision']
                            print(f"Loaded previous best precision: {best_precision:.4f}")
                        if 'best_recall' in checkpoint:
                            best_recall = checkpoint['best_recall']
                            print(f"Loaded previous best recall: {best_recall:.4f}")
                        if 'best_f1' in checkpoint:
                            best_f1 = checkpoint['best_f1']
                            print(f"Loaded previous best F1-score: {best_f1:.4f}")
                        if 'best_val_loss' in checkpoint:
                            best_val_loss = checkpoint['best_val_loss']
                            print(f"Loaded previous best val_loss: {best_val_loss:.4f}")
                        if 'no_improve_epochs' in checkpoint:
                            no_improve_epochs = checkpoint['no_improve_epochs']
                    except Exception as e2:
                        print(f"Could not load best metrics even with weights_only=False: {e2}")
                else:
                    print(f"Could not load best metrics: {e}")

        for epoch in range(Init_Epoch, UnFreeze_Epoch):
            if epoch >= Freeze_Epoch and not UnFreeze_flag and Freeze_Train:
                batch_size = Unfreeze_batch_size
                Init_lr_fit = min(max(batch_size / nbs * Init_lr, lr_limit_min), lr_limit_max)
                Min_lr_fit = min(max(batch_size / nbs * Min_lr, lr_limit_min * 1e-2), lr_limit_max * 1e-2)
                lr_scheduler_func = get_lr_scheduler(lr_decay_type, Init_lr_fit, Min_lr_fit, UnFreeze_Epoch)

                for param in model.backbone.parameters():
                    param.requires_grad = True

                epoch_step = num_train // batch_size
                epoch_step_val = num_val // batch_size
                if epoch_step == 0 or epoch_step_val == 0:
                    raise ValueError("数据集过小，无法继续进行训练，请扩充数据集。")
                    
                if ema:
                    ema.updates = epoch_step * epoch

                if distributed:
                    batch_size = batch_size // ngpus_per_node

                gen = DataLoader(train_dataset, shuffle=shuffle, batch_size=batch_size, num_workers=num_workers,
                                 pin_memory=True, drop_last=True, collate_fn=yolo_dataset_collate,
                                 sampler=train_sampler,
                                 worker_init_fn=partial(worker_init_fn, rank=rank, seed=seed),
                                 persistent_workers=True if num_workers > 0 else False,
                                 prefetch_factor=2 if num_workers > 0 else None)
                gen_val = DataLoader(val_dataset, shuffle=shuffle, batch_size=batch_size, num_workers=num_workers,
                                     pin_memory=True, drop_last=True, collate_fn=yolo_dataset_collate,
                                     sampler=val_sampler,
                                     worker_init_fn=partial(worker_init_fn, rank=rank, seed=seed),
                                     persistent_workers=True if num_workers > 0 else False,
                                     prefetch_factor=2 if num_workers > 0 else None)
                UnFreeze_flag = True

            gen.dataset.epoch_now = epoch
            gen_val.dataset.epoch_now = epoch
            if distributed:
                train_sampler.set_epoch(epoch)

            if epoch > UnFreeze_Epoch * 0.7:
                decay_factor = max(0.1, 1.0 - (epoch - UnFreeze_Epoch * 0.7) / (UnFreeze_Epoch * 0.3))
                current_mosaic_prob = mosaic_prob * decay_factor
                current_mixup_prob = mixup_prob * decay_factor
                gen.dataset.mosaic_prob = current_mosaic_prob
                gen.dataset.mixup_prob = current_mixup_prob
                if local_rank == 0 and epoch % 10 == 0:
                    print(f"Epoch {epoch}: Mosaic={current_mosaic_prob:.3f}, Mixup={current_mixup_prob:.3f}")

            set_optimizer_lr(optimizer, lr_scheduler_func, epoch)
            fit_result = fit_one_epoch(model_train, model, ema, yolo_loss, loss_history, eval_callback,
                                       optimizer, epoch, epoch_step, epoch_step_val, gen, gen_val,
                                       UnFreeze_Epoch, Cuda, fp16, scaler, save_period, save_dir, local_rank,
                                       epoch_offset=epoch_offset)

            if local_rank == 0 and fit_result is not None:
                print(f'Epoch:{epoch + 1}/{UnFreeze_Epoch} | Train time: {fit_result["train_time"]:.2f}s '
                      f'| Val time: {fit_result["val_time"]:.2f}s | Train loss: {fit_result["train_loss"]:.4f} '
                      f'| Val loss: {fit_result["val_loss"]:.4f} | LR: {get_lr(optimizer):.6f}')

                # 评估并判断是否更新最佳模型
                should_save_checkpoint = (epoch + 1) % save_period == 0 or (epoch + 1) == UnFreeze_Epoch

                current_map = 0
                current_precision = 0
                current_recall = 0
                current_f1 = 0

                if (epoch + 1) % eval_period == 0 and hasattr(eval_callback, 'metrics') and eval_callback.metrics:
                    print_detailed_metrics(eval_callback.metrics)
                    current_map = eval_callback.metrics.get('mAP', 0)
                    current_precision = eval_callback.metrics.get('precision', 0)
                    current_recall = eval_callback.metrics.get('recall', 0)
                    
                    if current_precision + current_recall > 0:
                        current_f1 = 2 * (current_precision * current_recall) / (current_precision + current_recall)
                    else:
                        current_f1 = 0

                    print(f'🔍 Epoch {epoch + 1}: Precision={current_precision:.4f}, Recall={current_recall:.4f}, F1-Score={current_f1:.4f}')

                    if current_recall >= min_recall_threshold and current_precision > best_precision:
                        print(f'\033[1;32m🏆 Epoch {epoch + 1}: Precision improved from {best_precision:.4f} to {current_precision:.4f}!\033[0m')
                        best_precision = current_precision
                    
                    if current_precision >= 0.8 and current_recall > best_recall:
                        print(f'\033[1;32m🔍 Epoch {epoch + 1}: Recall improved from {best_recall:.4f} to {current_recall:.4f}!\033[0m')
                        best_recall = current_recall
                    
                    if current_recall >= min_recall_threshold and current_f1 > best_f1 and current_f1 >= min_f1_threshold:
                        print(f'\033[1;32m🎯 Epoch {epoch + 1}: F1-score improved from {best_f1:.4f} to {current_f1:.4f}!\033[0m')
                        best_f1 = current_f1

                    if current_map > best_map:
                        print(f'\033[1;32m🏆 Epoch {epoch + 1}: mAP improved from {best_map:.4f} to {current_map:.4f}!\033[0m')
                        best_map = current_map

                # ========== 早停检查（解冻阶段生效）==========
                if early_stop_enabled and epoch >= Freeze_Epoch:
                    improved = False
                    if early_stop_metric == 'mAP':
                        # mAP 仅在评估轮次更新，非评估轮跳过检查
                        if (epoch + 1) % eval_period == 0:
                            improved = current_map > best_map
                    else:
                        # 默认监控验证损失，越低越好
                        if fit_result['val_loss'] < best_val_loss:
                            best_val_loss = fit_result['val_loss']
                            improved = True

                    if early_stop_metric == 'mAP' and (epoch + 1) % eval_period != 0:
                        pass  # 非评估轮不检查
                    else:
                        if improved:
                            no_improve_epochs = 0
                        else:
                            no_improve_epochs += 1
                            if no_improve_epochs % 5 == 0 or no_improve_epochs >= early_stop_patience:
                                print(f'⏸ 早停监控[{early_stop_metric}]: 已连续 {no_improve_epochs}/{early_stop_patience} 轮无改善 (最佳 {best_val_loss:.4f})')
                            if no_improve_epochs >= early_stop_patience:
                                print(f'\033[1;33m🛑 早停触发: 连续 {early_stop_patience} 轮 {early_stop_metric} 无改善，提前结束训练 (Epoch {epoch + 1})\033[0m')
                                break

                # ========== 保存完整 Checkpoint（用于断点续训）==========
                if should_save_checkpoint:
                    ckpt_path = os.path.join(save_dir, f"ep{epoch + 1 + epoch_offset}_ckpt.pt")
                    save_dict = {
                        'model': model.module.state_dict() if hasattr(model, 'module') else model.state_dict(),
                        'optimizer': optimizer.state_dict(),
                        'epoch': epoch + 1,
                        'ema': ema.ema.state_dict() if ema else None,
                        'best_map': best_map,
                        'best_precision': best_precision,
                        'best_recall': best_recall,
                        'best_f1': best_f1,
                        'best_val_loss': best_val_loss,
                        'no_improve_epochs': no_improve_epochs,
                        'input_shape': input_shape,
                        'num_classes': num_classes,
                        'phi': phi,
                        'classes_path': classes_path
                    }
                    torch.save(save_dict, ckpt_path)
                    print(f'\033[1;34m💾 Full checkpoint saved to {ckpt_path}\033[0m')

                # ========== 额外导出轻量部署模型（仅推理用）==========
                if export_deploy_model and current_precision == best_precision:
                    deploy_path = os.path.join(save_dir, "model_best_precision_deploy.pt")
                    deploy_dict = {
                        'model': ema.ema.state_dict() if ema else save_dict['model'],
                        'input_shape': input_shape,
                        'num_classes': num_classes,
                        'phi': phi
                    }
                    torch.save(deploy_dict, deploy_path)
                    print(f"\033[1;32m🚀 Deploy model updated at: {deploy_path}\033[0m")

            if Cuda and epoch % 5 == 0:
                torch.cuda.empty_cache()

            if distributed:
                dist.barrier()

        if local_rank == 0:
            loss_history.writer.close()


if __name__ == "__main__":
    # 支持两种方式启动：
    # 1. python train.py            -> 使用默认配置
    # 2. python train.py --config config_runtime.json  -> 使用指定配置文件
    if len(sys.argv) > 1 and sys.argv[1] == '--config':
        config_path = sys.argv[2]
        print(f"从配置文件加载: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    else:
        print("使用默认配置")
        cfg = get_config()

    print(f"数据集: {cfg['dataset_name']}")
    print(f"类别路径: {cfg['classes_path']}")
    print(f"模型: yolov8_{cfg['phi']}")
    print(f"训练轮次: {cfg['Init_Epoch']} - {cfg['UnFreeze_Epoch']}")
    print("=" * 60)

    train(cfg)
