#-- coding: utf-8 --
import os
import sys
sys.path.append('/data1/zl9/mtimg/yolov3-mxnet/core')
import time
import argparse
from utils import *
from darknet import DarkNet, TinyDarkNet
import pdb
import colorsys
from createXml import create
from PIL import Image, ImageFont, ImageDraw
import mxnet as mx
image_name = 0


def arg_parse():
    parser = argparse.ArgumentParser(description="YOLO v3 Detection Module")
    parser.add_argument("--images", dest='images', help=
    "Image / Directory containing images to perform detection upon",
                        default="", type=str)
    parser.add_argument("--video", dest='video', help=
    "video file path", type=str)
    parser.add_argument("--classes", dest="classes", default="data/coco.names", type=str)
    parser.add_argument("--gpu", dest="gpu", help="gpu id", default="0", type=str)
    parser.add_argument("--dst_dir", dest='dst_dir', help=
    "Image / Directory to store detections to", default="results", type=str)
    parser.add_argument("--batch_size", dest="batch_size", help="Batch size", default=16, type=int)
    parser.add_argument("--tiny", dest="tiny", help="use yolov3-tiny", default=False, type=bool)
    parser.add_argument("--confidence", dest="confidence", help="Object Confidence", default=0.50, type=float)
    parser.add_argument("--nms_thresh", dest="nms_thresh", help="NMS Threshhold", default=0.20, type=float)
    parser.add_argument("--params", dest='params', help=
    "params file", default="models/yolov3.weights", type=str)
    parser.add_argument("--input_dim", dest='input_dim', help=
    "Input resolution of the network. Increase to increase accuracy. Decrease to increase speed",
                        default=416, type=int)

    return parser.parse_args()


def parse_cfg(cfgfile):
    """
    Takes a configuration file

    Returns a list of blocks. Each blocks describes a block in the neural
    network to be built. Block is represented as a dictionary in the list

    """

    file = open(cfgfile, 'r')
    lines = file.read().split('\n')  # store the lines in a list
    lines = [x for x in lines if len(x) > 0]  # get read of the empty lines
    lines = [x for x in lines if x[0] != '#']  # get rid of comments
    lines = [x.rstrip().lstrip() for x in lines]  # get rid of fringe whitespaces

    block = {}
    blocks = []

    for line in lines:
        if line[0] == "[":  # This marks the start of a new block
            if len(block) != 0:  # If block is not empty, implies it is storing values of previous block.
                blocks.append(block)  # add it the blocks list
                block = {}  # re-init the block
            block["type"] = line[1:-1].rstrip()
        else:
            key, value = line.split("=")
            block[key.rstrip()] = value.lstrip()
    blocks.append(block)

    return blocks


def draw_bbox(img, bboxs):
   for x in bboxs:
	cls = int(x[-1])
	predicted_class = classes[cls]  # 类别
    	box = x[1:5]  # 框
    	score = x[-2]  # 执行度

    	label = '{} {:.2f}'.format(predicted_class, score)  # 标签

	top, left, bottom, right = box
	top = max(0, np.floor(top + 0.5).astype('int32'))
    	left = max(0, np.floor(left + 0.5).astype('int32'))
    	bottom = min(img.shape[1], np.floor(bottom + 0.5).astype('int32'))
    	right = min(img.shape[0], np.floor(right + 0.5).astype('int32'))

	c1 = (top,left)
	c2 = (bottom,right)
	cv2.rectangle(img,c1, c2,colors[cls],4)
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 2, 2)[0]
        c2 = c1[0] + t_size[0] + 20, c1[1] - t_size[1] - 20
        cv2.rectangle(img, c1, c2, colors[cls], -1)
        cv2.putText(img, label, (c1[0], c1[1] - t_size[1] + 5), cv2.FONT_HERSHEY_PLAIN, 2, [0, 0, 0], 1)
   
   return img

def save_results(load_images, images_name,output, input_dim):

    im_dim_list = nd.array([(x.shape[1], x.shape[0]) for x in load_images])
    im_dim_list = nd.tile(im_dim_list, 2)
    im_dim_list = im_dim_list[output[:, 0], :]

    scaling_factor = nd.min(input_dim / im_dim_list, axis=1).reshape((-1, 1))
    # scaling_factor = (416 / im_dim_list)[0].view(-1, 1)

    output[:, [1, 3]] -= (input_dim - scaling_factor * im_dim_list[:, 0].reshape((-1, 1))) / 2
    output[:, [2, 4]] -= (input_dim - scaling_factor * im_dim_list[:, 1].reshape((-1, 1))) / 2
    output[:, 1:5] /= scaling_factor

    for i in range(output.shape[0]):
        output[i, [1, 3]] = nd.clip(output[i, [1, 3]], a_min=0.0, a_max=im_dim_list[i][0].asscalar())
        output[i, [2, 4]] = nd.clip(output[i, [2, 4]], a_min=0.0, a_max=im_dim_list[i][1].asscalar())

    output = output.asnumpy()
    

    for i in range(len(load_images)):
        bboxs = []
        for bbox in output:
            if i == int(bbox[0]):
                bboxs.append(bbox)
        draw_bbox(load_images[i], bboxs)
    	xml_path = '/'
    	img_shape = [load_images[i].shape[1],load_images[i].shape[0],3]
    	create(xml_path,images_name[i],img_shape,bboxs,classes)

    global image_name
    list(map(cv2.imwrite, [os.path.join(dst_dir, "{0}.jpg".format(images_name[i])) for i in range(len(load_images))], load_images))
    image_name += len(load_images)


def predict_video(net, ctx, video_file, anchors):
    if video_file:
        cap = cv2.VideoCapture(video_file)
    else:
        cap = cv2.VideoCapture(0)

    assert cap.isOpened(), 'Cannot capture source'

    result_video = cv2.VideoWriter(
        os.path.join(dst_dir, "result.avi"),
        cv2.VideoWriter_fourcc("X", "2", "6", "4"),
        25,
        (1280, 720)
    )

    detect_start = time.time()
    frame_num = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if ret:
            frame_num += 1
            if frame_num % 5 != 0:
                continue
            frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_CUBIC)
            img = nd.array(prep_image(frame, input_dim), ctx=ctx).expand_dims(0)

            prediction = predict_transform(net(img), input_dim, anchors)
            prediction = write_results(prediction, num_classes, confidence=confidence, nms_conf=nms_thresh)

            if prediction is None:
                result_video.write(frame)
                continue

            scaling_factor = min(input_dim / frame.shape[0], input_dim / frame.shape[1])

            prediction[:, [1, 3]] -= (input_dim - scaling_factor * frame.shape[1]) / 2
            prediction[:, [2, 4]] -= (input_dim - scaling_factor * frame.shape[0]) / 2
            prediction[:, 1:5] /= scaling_factor

            for i in range(prediction.shape[0]):
                prediction[i, [1, 3]] = nd.clip(prediction[i, [1, 3]], 0.0, frame.shape[1])
                prediction[i, [2, 4]] = nd.clip(prediction[i, [2, 4]], 0.0, frame.shape[0])

            prediction = prediction.asnumpy()
            draw_bbox(frame, prediction)

            result_video.write(frame)

            # cv2.imshow("frame", frame)
            # key = cv2.waitKey(1000)
            # if key & 0xFF == ord('q'):
            #     break
            # print(time.time() - start)
            if frame_num % 100 == 0:
                t = time.time() - detect_start
                print("FPS of the video is {:5.2f}\nPer Image Cost Time {:5.3f}".format(100 / t,
                                                                                        t / 100))
                detect_start = time.time()

        else:
            print("video source closed")
            break
    result_video.release()
    print("{0} detect complete".format(video_file))


if __name__ == '__main__':

    np.set_printoptions(suppress=True)
    args = arg_parse()
    images = args.images
    batch_size = args.batch_size
    confidence = args.confidence
    nms_thresh = args.nms_thresh
    input_dim = args.input_dim
    dst_dir = args.dst_dir
    start = 0
    classes = load_classes(args.classes)

    gpu = [int(x) for x in args.gpu.replace(" ", "").split(",")]
    ctx = try_gpu(args.gpu)[0]
    #ctx = mx.cpu()
    num_classes = len(classes)
    if args.tiny:
        net = TinyDarkNet(input_dim=input_dim, num_classes=num_classes)
        anchors = np.array([(10, 14), (23, 27), (37, 58), (81, 82), (135, 169), (344, 319)])
    else:
        net = DarkNet(input_dim=input_dim, num_classes=num_classes)
        anchors = np.array([(10, 13), (16, 30), (33, 23), (30, 61), (62, 45),
                            (59, 119), (116, 90), (156, 198), (373, 326)])
    net.initialize(ctx=ctx)
    input_dim = args.input_dim

    try:
        imlist = [os.path.join(images, img) for img in os.listdir(images)]
    except NotADirectoryError:
        imlist = []
    except FileNotFoundError:
        print("No file or directory with the name {}".format(images))

    if not os.path.exists(dst_dir):
        os.mkdir(dst_dir)

    if args.params.endswith(".params"):
        net.load_params(args.params)
    elif args.params.endswith(".weights"):
        tmp_batch = nd.uniform(shape=(1, 3, args.input_dim, args.input_dim), ctx=ctx)
        net(tmp_batch)
        net.load_weights(args.params, fine_tune=False)
    else:
        print("params {} load error!".format(args.params))
        exit()
    print("load params: {}".format(args.params))
    net.hybridize()

    if args.video:
        predict_video(net, ctx=ctx, video_file=args.video, anchors=anchors)
        exit()

    if not imlist:
        print("no images to detect")
        exit()
    print(len(imlist))
    leftover = 0
    if len(imlist) % batch_size:
        leftover = 1

    num_batches = len(imlist) // batch_size + leftover
    im_batches = [imlist[i * batch_size: min((i + 1) * batch_size, len(imlist))]
                  for i in range(num_batches)]

    start_det_loop = time.time()

    global colors

    hsv_tuples = [(float(x) / num_classes, 1., 1.)  for x in range(num_classes)]  # 不同颜色
    colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
    colors = list(map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), colors))  # RGB

    output = None
    for i, batch in enumerate(im_batches):
	images_name = [img.split('/')[-1] for img in batch]
        load_images = [cv2.imread(img) for img in batch]
        tmp_batch = list(map(prep_image, load_images, [input_dim for x in range(len(batch))]))
        tmp_batch = nd.array(tmp_batch, ctx=ctx)
        start = time.time()
        prediction = predict_transform(net(tmp_batch), input_dim, anchors)
        prediction = write_results(prediction, num_classes, confidence=confidence, nms_conf=nms_thresh)

        end = time.time()

        if output is None:
            output = prediction
        else:
            output = nd.concat(output, prediction, dim=0)

        print("{0} predicted in {1:6.3f} seconds".format(len(load_images), (end - start) / len(batch)))
        print("----------------------------------------------------------")

        if output is not None:
            save_results(load_images, images_name,output, input_dim=input_dim)
        else:
            print("No detections were made")
        output = None
