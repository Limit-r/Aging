import os
import time
import torch
from utils.utils import get_lr

def fit_one_epoch(model_train, model, ema, yolo_loss, loss_history, eval_callback, optimizer, epoch, epoch_step, epoch_step_val, gen, gen_val, Epoch, cuda, fp16, scaler, save_period, save_dir, local_rank=0, epoch_offset=0):
    loss        = 0
    val_loss    = 0

    # 训练阶段
    model_train.train()
    train_start_time = time.time()
    for iteration, batch in enumerate(gen):
        if iteration >= epoch_step:
            break

        images, bboxes = batch
        with torch.no_grad():
            if cuda:
                images = images.cuda(local_rank)
                bboxes = bboxes.cuda(local_rank)
                
        # 清零梯度
        optimizer.zero_grad()
        if not fp16:
            # 前向传播
            outputs = model_train(images)
            loss_value = yolo_loss(outputs, bboxes)
            # 反向传播
            loss_value.backward()
            torch.nn.utils.clip_grad_norm_(model_train.parameters(), max_norm=10.0)  # clip gradients
            
            optimizer.step()
        else:
            from torch.amp import autocast
            with autocast('cuda'):
                # 前向传播
                outputs = model_train(images)
                loss_value = yolo_loss(outputs, bboxes)

            # 反向传播
            scaler.scale(loss_value).backward()
            scaler.unscale_(optimizer)  # unscale gradients
            torch.nn.utils.clip_grad_norm_(model_train.parameters(), max_norm=10.0)  # clip gradients
            scaler.step(optimizer)
            scaler.update()
            
        if ema:
            ema.update(model_train)

        loss += loss_value.item()
        
        # 定期清理内存
        if iteration % 10 == 0 and cuda:
            torch.cuda.empty_cache()
    
    train_time = time.time() - train_start_time

    # 验证阶段
    if ema:
        model_train_eval = ema.ema
    else:
        model_train_eval = model_train.eval()
        
    val_start_time = time.time()
    for iteration, batch in enumerate(gen_val):
        if iteration >= epoch_step_val:
            break
        images, bboxes = batch[0], batch[1]
        with torch.no_grad():
            if cuda:
                images = images.cuda(local_rank)
                bboxes = bboxes.cuda(local_rank)
            # 清零梯度
            optimizer.zero_grad()
            # 前向传播
            outputs     = model_train_eval(images)
            loss_value  = yolo_loss(outputs, bboxes)

        val_loss += loss_value.item()
        
        # 定期清理内存
        if iteration % 10 == 0 and cuda:
            torch.cuda.empty_cache()
            
    val_time = time.time() - val_start_time
        
    # 记录loss
    train_loss = loss / epoch_step
    validation_loss = val_loss / epoch_step_val
    
    # 返回训练结果用于主循环输出
    fit_result = {
        'train_loss': train_loss,
        'val_loss': validation_loss,
        'train_time': train_time,
        'val_time': val_time
    }
    
    loss_history.append_loss(epoch + 1, train_loss, validation_loss)
    eval_callback.on_epoch_end(epoch + 1, model_train_eval)
        
    # 保存权值
    if local_rank == 0:
        if ema:
            save_state_dict = ema.ema.state_dict()
        else:
            save_state_dict = model.state_dict()

        if (epoch + 1) % save_period == 0 or epoch + 1 == Epoch:
            torch.save(save_state_dict, os.path.join(save_dir, "ep%03d-loss%.3f-val_loss%.3f.pth" % (epoch + 1 + epoch_offset, train_loss, validation_loss)))
            
        # 保存最佳模型
        if len(loss_history.val_loss) <= 1 or (validation_loss) <= min(loss_history.val_loss):
            torch.save(save_state_dict, os.path.join(save_dir, "best_epoch_weights.pth"))
            
        torch.save(save_state_dict, os.path.join(save_dir, "last_epoch_weights.pth"))
        
    # 每个epoch结束后清理内存
    if cuda:
        torch.cuda.empty_cache()
        
    return fit_result

def print_detailed_metrics(metrics):
    """
    打印详细的评估指标
    """
    if metrics:
        print("="*60)
        print("Detailed Evaluation Metrics:")
        print("="*60)
        
        # 打印总体指标
        if 'mAP' in metrics:
            print(f"mAP (mean Average Precision): {metrics['mAP']:.4f}")
        if 'precision' in metrics:
            print(f"Precision (准确率): {metrics['precision']:.4f}")
        if 'recall' in metrics:
            print(f"Recall (召回率): {metrics['recall']:.4f}")
        if 'f1_score' in metrics:
            print(f"F1-Score (F1分数): {metrics['f1_score']:.4f}")
        if 'confidence' in metrics:
            print(f"Average Confidence (平均置信度): {metrics['confidence']:.4f}")
            
        # 打印每个类别的指标
        if 'class_metrics' in metrics:
            print("\nPer-Class Metrics:")
            for class_name, class_metrics in metrics['class_metrics'].items():
                print(f"  {class_name}:")
                for metric_name, metric_value in class_metrics.items():
                    if metric_name == 'precision':
                        print(f"    Precision (准确率): {metric_value:.4f}")
                    elif metric_name == 'recall':
                        print(f"    Recall (召回率): {metric_value:.4f}")
                    elif metric_name == 'f1_score':
                        print(f"    F1-Score (F1分数): {metric_value:.4f}")
                    elif metric_name == 'avg_confidence':
                        print(f"    Average Confidence (平均置信度): {metric_value:.4f}")
                    elif metric_name == 'count':
                        print(f"    Detection Count (检测数量): {metric_value}")
                        
        print("="*60)