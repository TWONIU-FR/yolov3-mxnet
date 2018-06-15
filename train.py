import re
import threading
import time
import xml.etree.ElementTree as ET
from random import shuffle
from mxnet import autograd
from mxnet import gluon
from darknet_mxnet import DarkNet
from util_mxnet import *


def parse_xml(xml_file, classes):
    root = ET.parse(xml_file).getroot()
    label = {}
    image_size = root.find("size")
    size = {
        "width": float(image_size.find("width").text),
        "height": float(image_size.find("height").text),
        "depth": float(image_size.find("depth").text)
    }
    label["size"] = size
    bbox = []
    if not isinstance(classes, np.ndarray):
        classes = np.array(classes)
    for obj in root.findall("object"):
        cls = (classes == obj.find("name").text).astype(np.float)
        bndbox = obj.find("bndbox")
        xmin = float(bndbox.find("xmin").text)
        ymin = float(bndbox.find("ymin").text)
        xmax = float(bndbox.find("xmax").text)
        ymax = float(bndbox.find("ymax").text)
        center_x = (xmin + xmax) / 2.0 / size["width"]
        center_y = (ymin + ymax) / 2.0 / size["height"]
        width = (xmax - xmin) / size["width"]
        height = (ymax - ymin) / size["height"]
        bbox.append(np.hstack(([center_x, center_y, width, height, 1.0], cls)))
    label["bbox"] = np.array(bbox)
    return np.array(bbox)


def prep_label(label_file, num_classes, ctx):
    with open(label_file, "r") as file:
        labels = file.readlines()
        labels = np.array([list(map(float, x.split())) for x in labels], dtype="float32")
        final_labels = nd.zeros(shape=(30, num_classes + 5), dtype="float32", ctx=ctx)
        i = 0
        for label in labels:
            one_hot = np.zeros(shape=(num_classes + 5), dtype="float32")
            one_hot[5 + int(label[0])] = 1.0
            one_hot[4] = 1.0
            one_hot[:4] = label[1:]
            final_labels[i] = one_hot
            i += 1
            i %= 30
        return nd.array(final_labels, ctx=ctx)


def prep_final_label(labels, num_classes, ctx):
    if isinstance(labels, nd.NDArray):
        labels = labels.asnumpy()
    input_dim = 416.0
    anchors = np.array([(10, 13), (16, 30), (33, 23), (30, 61), (62, 45),
                        (59, 119), (116, 90), (156, 198), (373, 326)])
    batch_size = labels.shape[0]
    label_1 = np.zeros(shape=(batch_size, 13, 13, 3, num_classes + 5), dtype="float32")
    label_2 = np.zeros(shape=(batch_size, 26, 26, 3, num_classes + 5), dtype="float32")
    label_3 = np.zeros(shape=(batch_size, 52, 52, 3, num_classes + 5), dtype="float32")

    true_label_1 = np.zeros(shape=(batch_size, 13, 13, 3, 5), dtype="float32")
    true_label_2 = np.zeros(shape=(batch_size, 26, 26, 3, 5), dtype="float32")
    true_label_3 = np.zeros(shape=(batch_size, 52, 52, 3, 5), dtype="float32")
    label_list = [label_3, label_2, label_1]
    true_label_list = [true_label_3, true_label_2, true_label_1]
    for x_box in range(labels.shape[0]):
        for y_box in range(labels.shape[1]):
            if labels[x_box, y_box, 4] == 0.0:
                break

            tmp_xywh = np.repeat(np.expand_dims(labels[x_box, y_box, :4] * input_dim, axis=0), repeats=anchors.shape[0], axis=0)
            anchor_xywh = tmp_xywh.copy()
            anchor_xywh[:, 2:4] = anchors
            best_anchor = np.argmax(bbox_iou(tmp_xywh, anchor_xywh), axis=0)
            grid_shape = np.power(2, 2 - best_anchor // 3) * 13
            label = labels[x_box, y_box].copy()
            tmp_idx = (label[:2] * grid_shape).astype("int")
            label[:2] = label[:2] * grid_shape
            label[:2] -= np.floor(label[:2])
            label[2:4] = np.log(label[2:4] * input_dim / anchors[best_anchor])
            label[np.isnan(label)] = 0.
            label_list[best_anchor // 3][x_box, tmp_idx[1], tmp_idx[0], best_anchor % 3] = label

            true_xywhs = labels[x_box, y_box, :5] * input_dim
            true_xywhs[4] = 1.0
            true_label_list[best_anchor // 3][x_box, tmp_idx[1], tmp_idx[0], best_anchor % 3] = true_xywhs
    t_y = nd.concat(nd.array(label_1.reshape((batch_size, -1, num_classes + 5)), ctx=ctx),
                     nd.array(label_2.reshape((batch_size, -1, num_classes + 5)), ctx=ctx),
                     nd.array(label_3.reshape((batch_size, -1, num_classes + 5)), ctx=ctx),
                     dim=1)
    t_xywhs = nd.concat(nd.array(true_label_1.reshape((batch_size, -1, 5)), ctx=ctx),
                     nd.array(true_label_2.reshape((batch_size, -1, 5)), ctx=ctx),
                     nd.array(true_label_3.reshape((batch_size, -1, 5)), ctx=ctx),
                     dim=1)

    return t_y, t_xywhs


class YoloDataSet(gluon.data.Dataset):
    def __init__(self, images_file, classes, input_dim=416, is_shuffle=False, ctx=mx.cpu()):
        super(YoloDataSet, self).__init__()
        self.anchors = [(10, 13), (16, 30), (33, 23), (30, 61), (62, 45),
                        (59, 119), (116, 90), (156, 198), (373, 326)]
        self.classes = classes
        self.input_dim = input_dim
        self.ctx = ctx
        with open(images_file, "r") as file:
            self.image_list = file.readlines()
        self.image_list = [im.strip() for im in self.image_list]
        if is_shuffle:
            shuffle(self.image_list)
        pattern = re.compile("(\.png|\.jpg|\.bmp|\.jpeg)")
        self.label_list = []
        for i in range(len(self.image_list) - 1, -1, -1):
            if pattern.search(self.image_list[i]) is None:
                self.image_list.pop(i)
                continue
            label = pattern.sub(lambda s: ".txt", self.image_list[i]).replace("JPEGImages", "labels")
            # if not os.path.exists(label):
            #     self.image_list.pop(i)
            self.label_list.append(label)

    def __len__(self):
        return len(self.image_list)

    def __getitem__(self, idx):
        image = cv2.imread(self.image_list[idx])
        image = prep_image(image, self.input_dim, self.ctx)
        label = prep_label(self.label_list[idx], num_classes=len(self.classes), ctx=self.ctx)
        return image.squeeze(), label.squeeze()


class LossRecorder(mx.metric.EvalMetric):
    """LossRecorder is used to record raw loss so we can observe loss directly
    """

    def __init__(self, name):
        super(LossRecorder, self).__init__(name)

    def update(self, labels, preds=0):
        """Update metric with pure loss
        """
        for loss in labels:
            if isinstance(loss, mx.nd.NDArray):
                loss = loss.asnumpy()
            self.sum_metric += loss.sum()
            self.num_inst += 1


class MyThread(threading.Thread):
    def __init__(self, func, args=()):
        super(MyThread, self).__init__()
        self.func = func
        self.args = args

    def run(self):
        self.result = self.func(*self.args)

    def get_result(self):
        try:
            return self.result  # 如果子线程不使用join方法，此处可能会报没有self.result的错误
        except Exception as e:
            print(e)
            return None


def calculate_ignore(xywh, true_xywhs):
    if isinstance(xywh, nd.NDArray):
        xywh = xywh.asnumpy()
    if isinstance(true_xywhs, nd.NDArray):
        true_xywhs = true_xywhs.asnumpy()
    xywh[np.isnan(xywh)] = 0.
    ignore_mask = np.ones(shape=pred_score.shape, dtype="float32")
    iou_score_single_time = 0
    item_index = np.argwhere(true_xywhs[:, :, 4] == 1.0)
    for x_box, y_box in item_index:
        iou_score_start = time.time()
        iou = bbox_iou(xywh[x_box, y_box:y_box + 1], true_xywhs[x_box, y_box:y_box + 1]) < 0.6
        ignore_mask[x_box, y_box:y_box + 1] = iou.astype("float32").reshape((-1, 1))
        iou_score_single_time += time.time() - iou_score_start
    print("iou score single time: {}".format(iou_score_single_time))
    return ignore_mask


if __name__ == '__main__':
    classes = ["aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair",
               "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant",
               "sheep", "sofa", "train", "tvmonitor"]
    num_classes = len(classes)
    ctx = [mx.gpu(4)]
    batch_size = 32 * len(ctx)
    dataset = YoloDataSet("./data/train.txt", classes=classes, is_shuffle=True, ctx=ctx[0])
    train_data = gluon.data.DataLoader(dataset, batch_size=batch_size)
    sce_loss = gluon.loss.SigmoidBCELoss(from_sigmoid=True)
    l1_loss = gluon.loss.L1Loss()
    l2_loss = gluon.loss.L2Loss()

    obj_loss = LossRecorder('objectness_loss')
    cls_loss = LossRecorder('classification_loss')
    box_loss = LossRecorder('box_refine_loss')
    positive_weight = 1.0
    negative_weight = 0.5
    class_weight = 1.0
    box_weight = 5.0

    net = DarkNet(num_classes=len(classes))
    net.initialize(ctx=ctx)
    X = nd.uniform(shape=(2, 3, 416, 416), ctx=ctx[0])
    net(X)
    net.load_weights("./yolov3.weights")
    anchors = np.array([(10, 13), (16, 30), (33, 23), (30, 61), (62, 45),
                        (59, 119), (116, 90), (156, 198), (373, 326)])
    adam = mx.optimizer.Optimizer.create_optimizer("adam")
    finetune_lr = dict({"conv_{}_weight".format(k): 1e-3 for k in [56, 57, 58, 64, 65, 66, 72, 73, 74]})
    lr2 = dict({"conv_{}_bias".format(k): 1e-3 for k in [56, 57, 58, 64, 65, 66, 72, 73, 74]})
    adam.set_learning_rate(1e-5)
    adam.set_lr_mult({**finetune_lr, **lr2})
    trainer = gluon.Trainer(net.collect_params(), optimizer=adam)

    for epoch in range(200):  # reset data iterators and metrics
        cls_loss.reset()
        obj_loss.reset()
        box_loss.reset()
        tic = time.time()
        for i, batch in enumerate(train_data):
            gpu_x = split_and_load(batch[0], ctx)
            gpu_y = split_and_load(batch[1], ctx)
            record_pause = 0

            def record(t_x):
                ele_num = 3 * (5 + num_classes)
                prediction = [t_x[:, :ele_num * 13 * 13],
                              t_x[:, ele_num * 13 * 13: ele_num * (13 * 13 + 26 * 26)],
                              t_x[:, ele_num * (13 * 13 + 26 * 26):]]
                anchors_mask = [[6, 7, 8], [3, 4, 5], [0, 1, 2]]
                xy = None
                wh = None
                score = None
                cls_pred = None
                for j in range(0, 3):
                    tmp_anchors = anchors[anchors_mask[j]]
                    tmp_xy, tmp_wh, tmp_score, tmp_cls = predict_transform(prediction[j], 416, tmp_anchors,
                                                                     num_classes, stride=416 // (pow(2, j) * 13),
                                                                     is_train=True)
                    if xy is None:
                        xy = tmp_xy
                    else:
                        xy = nd.concat(xy, tmp_xy, dim=1)
                    if wh is None:
                        wh = tmp_wh
                    else:
                        wh = nd.concat(wh, tmp_wh, dim=1)
                    if score is None:
                        score = tmp_score
                    else:
                        score = nd.concat(score, tmp_score, dim=1)
                    if cls_pred is None:
                        cls_pred = tmp_cls
                    else:
                        cls_pred = nd.concat(cls_pred, tmp_cls, dim=1)
                return xy, wh, score, cls_pred


            with autograd.record():
                prediction_list = [record(net(t_x)) for t_x in gpu_x]
                for p_i in range(len(prediction_list)):
                    pred_xy, pred_wh, pred_score, pred_cls = prediction_list[p_i]
                    with autograd.pause():
                        t_y, true_xywhs = prep_final_label(gpu_y[p_i], num_classes, ctx=pred_xy.context)
                        ignore_mask = nd.array(calculate_ignore(nd.concat(pred_xy, pred_wh, dim=2).asnumpy(), true_xywhs)
                                               , ctx=pred_xy.context)
                        tbox = t_y[:, :, :4]
                        tscore = t_y[:, :, 4].reshape(0, -1, 1)
                        tid = t_y[:, :, 5:]
                        coordinate_weight = (tscore != 0.0).astype("float32")
                        score_weight = nd.where(coordinate_weight == 1.0,
                                                nd.ones_like(coordinate_weight) * positive_weight,
                                                nd.ones_like(coordinate_weight) * negative_weight)

                    # wh = nd.sqrt(nd.abs(xywh.slice_axis(begin=2, end=4, axis=-1)) + 0.01)
                    zero_scale = 10647 / nd.mean(nd.sum(tscore, axis=1)).asscalar()
                    box_loss_scale = 2 - t_y[:, :, 2:3] * t_y[:, :, 3:4]
                    item_index = np.argwhere(tscore.asnumpy() != 0.0)

                    loss1 = sce_loss(pred_cls, tid) * coordinate_weight * class_weight
                    loss2 = sce_loss(pred_score, tscore) * score_weight * coordinate_weight * ignore_mask
                    loss3 = sce_loss(pred_xy, tbox.slice_axis(begin=0, end=2, axis=-1)) * coordinate_weight * box_loss_scale
                    loss4 = nd.square(tbox.slice_axis(begin=2, end=4, axis=-1) - pred_wh) * coordinate_weight \
                            * 0.5 * box_loss_scale

                    loss1 = nd.nansum(loss1) / batch_size
                    loss2 = nd.nansum(loss2) / batch_size
                    loss3 = nd.nansum(loss3) / batch_size
                    loss4 = nd.nansum(loss4) / batch_size

                    tmp_cls = pred_cls[item_index[0][0], item_index[0][1]]
                    tmp_score = pred_score[item_index[0][0], item_index[0][1]]
                    item_index = np.argwhere(tid.asnumpy()[item_index[0][0], item_index[0][1]] == 1.0)
                    print(tmp_cls[item_index[0]])
                    print(tmp_score)

                    loss = loss1 + loss2 + loss3 + loss4
                    loss.backward()
                    cls_loss.update(loss1)
                    obj_loss.update(loss2)
                    box_loss.update(loss3 + loss4)
                    print("cls_loss: {:.5f}\nobj_loss: {:.5f}\nbox_loss: {:.5f}\n"
                          .format(loss1.asscalar(), loss2.asscalar(), (loss3 + loss4).asscalar()))
            trainer.step(batch_size)
            print("batch: {} / {}".format(i, np.ceil(len(dataset) / batch_size)))
        nd.waitall()
        print('Epoch %2d, train %s %.5f, %s %.5f, %s %.5f time %.1f sec' % (
            epoch, *cls_loss.get(), *obj_loss.get(), *box_loss.get(), time.time() - tic))
        loss = cls_loss.get()[1] + obj_loss.get()[1] + box_loss.get()[1]
        net.save_params("./models/yolov3_{}_loss_{:.3f}.params".format(epoch, loss))
