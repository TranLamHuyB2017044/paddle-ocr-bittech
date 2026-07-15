
import logging
import copy
import time
import os

from huggingface_hub import snapshot_download

from ..utils.file_utils import get_project_base_directory
from ..utils.settings import PARALLEL_DEVICES
from .operators import *  # noqa: F403
from . import operators
import numpy as np
import cv2
import onnxruntime as ort
import torch
from PIL import Image
from vietocr.tool.config import Cfg
from vietocr.tool.translate import build_model
import torch

from .postprocess import build_post_process

loaded_models = {}

current_dir = os.path.dirname(os.path.abspath(__file__))
deepdoc_dir = os.path.dirname(current_dir)
config = Cfg.load_config_from_name('vgg_seq2seq')
config['cnn']['pretrained']=False
config['device'] = 'cpu'
# weight_path = './weight/transformerocr.pth'

# build model
model, vocab = build_model(config)

# load weight
# model.load_state_dict(torch.load(weight_path, map_location=torch.device(config['device'])))
# model = model.eval()

def is_valid_crop(img_crop, min_w=6, min_h=6, min_blur_var=10.0):
    """
    Checks if a cropped text image is valid (not too small, not too blurry).
    """
    if img_crop is None or img_crop.size == 0:
        return False
    h, w = img_crop.shape[:2]
    if w < min_w or h < min_h:
        return False
    # Check blurriness for crops that are large enough (to avoid false positives on small but sharp dots)
    if w > 15 and h > 15:
        gray = cv2.cvtColor(img_crop, cv2.COLOR_BGR2GRAY) if img_crop.ndim == 3 else img_crop
        var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if var < min_blur_var:
            return False
    return True


def transform(data, ops=None):
    """ transform """
    if ops is None:
        ops = []
    for op in ops:
        data = op(data)
        if data is None:
            return None
    return data


def create_operators(op_param_list, global_config=None):
    """
    create operators based on the config

    Args:
        params(list): a dict list, used to create some operators
    """
    assert isinstance(
        op_param_list, list), ('operator config should be a list')
    ops = []
    for operator in op_param_list:
        assert isinstance(operator,
                          dict) and len(operator) == 1, "yaml format error"
        op_name = list(operator)[0]
        param = {} if operator[op_name] is None else operator[op_name]
        if global_config is not None:
            param.update(global_config)
        op = getattr(operators, op_name)(**param)
        ops.append(op)
    return ops


def load_model(model_dir, nm, device_id: int | None = None):
    model_file_path = os.path.join(model_dir, nm + ".onnx")
    model_cached_tag = model_file_path + str(device_id) if device_id is not None else model_file_path

    global loaded_models
    loaded_model = loaded_models.get(model_cached_tag)
    if loaded_model:
        logging.info(f"load_model {model_file_path} reuses cached model")
        return loaded_model

    if not os.path.exists(model_file_path):
        raise ValueError("not find model file path {}".format(
            model_file_path))

    def cuda_is_available():
        try:
            import torch
            if torch.cuda.is_available() and device_id is not None and torch.cuda.device_count() > device_id:
                return True
        except Exception:
            return False
        return False

    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 2

    # https://github.com/microsoft/onnxruntime/issues/9509#issuecomment-951546580
    # Shrink GPU memory after execution
    run_options = ort.RunOptions()
    if cuda_is_available():
        cuda_provider_options = {
            "device_id": device_id, # Use specific GPU
            "gpu_mem_limit": 512 * 1024 * 1024, # Limit gpu memory
            "arena_extend_strategy": "kNextPowerOfTwo",  # gpu memory allocation strategy
        }
        sess = ort.InferenceSession(
            model_file_path,
            options=options,
            providers=['CUDAExecutionProvider'],
            provider_options=[cuda_provider_options]
            )
        run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:" + str(device_id))
        logging.info(f"load_model {model_file_path} uses GPU")
    else:
        sess = ort.InferenceSession(
            model_file_path,
            options=options,
            providers=['CPUExecutionProvider'])
        run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu")
        logging.info(f"load_model {model_file_path} uses CPU")
    loaded_model = (sess, run_options)
    loaded_models[model_cached_tag] = loaded_model
    return loaded_model

#Add ONNX vietocr
def translate_onnx(img, session, max_seq_length=64, sos_token=1, eos_token=2):
    """data: BxCxHxW"""
    cnn_session, encoder_session, decoder_session = session

    # create cnn input
    cnn_input = {cnn_session.get_inputs()[0].name: img}
    src = cnn_session.run(None, cnn_input)

    # create encoder input
    encoder_input = {encoder_session.get_inputs()[0].name: src[0]}
    encoder_outputs, hidden = encoder_session.run(None, encoder_input)
    translated_sentence = [[sos_token] * len(img)]
    max_length = 0

    while max_length <= max_seq_length and not all(
        np.any(np.asarray(translated_sentence).T == eos_token, axis=1)
    ):
        tgt_inp = translated_sentence
        decoder_input = {
            decoder_session.get_inputs()[0].name: tgt_inp[-1],
            decoder_session.get_inputs()[1].name: hidden,
            decoder_session.get_inputs()[2].name: encoder_outputs
        }

        output, hidden, _ = decoder_session.run(None, decoder_input)
        
        # Pure NumPy argmax to avoid PyTorch overhead on CPU
        indices = np.argmax(output, axis=-1).tolist()

        translated_sentence.append(indices)
        max_length += 1

    translated_sentence = np.asarray(translated_sentence).T

    return translated_sentence

class TextRecognizer:
    def __init__(self, _model_dir=None, _device_id: int | None = None):
        # Load ONNX sessions for CNN, encoder, and decoder
        vietocr_weight_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vietocr", "weight")
        
        # Set session options to reduce log noise
        options = ort.SessionOptions()
        options.log_severity_level = 3  # 0:Verbose, 1:Info, 2:Warning, 3:Error, 4:Fatal
        
        self.cnn_session = ort.InferenceSession(os.path.join(vietocr_weight_dir, "cnn.onnx"), sess_options=options)
        self.encoder_session = ort.InferenceSession(os.path.join(vietocr_weight_dir, "encoder.onnx"), sess_options=options)
        self.decoder_session = ort.InferenceSession(os.path.join(vietocr_weight_dir, "decoder.onnx"), sess_options=options)
        self.session = (self.cnn_session, self.encoder_session, self.decoder_session)
        # You may need to load vocab here, e.g., self.vocab = ... 

    def __call__(self, img_list):
        if not img_list:
            return [], 0.0

        st = time.time()
        
        # Parallel execution using ThreadPoolExecutor
        # (ONNX Runtime releases the GIL during inference, allowing true CPU concurrency)
        from concurrent.futures import ThreadPoolExecutor
        
        # Default to 4 threads; can be adjusted via OCR_THREADS env variable
        num_threads = int(os.getenv("OCR_THREADS", "4"))
        
        def recognize_single(img):
            # Ensure image is RGB
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # Resize to height 32, keep aspect ratio
            h, w, c = img.shape
            new_h = 32
            new_w = max(8, int(w * (new_h / h)))
            img_resized = cv2.resize(img, (new_w, new_h))

            # Transpose to (C, H, W)
            img_resized = img_resized.transpose(2, 0, 1)
            # Normalize to float32 [0, 1]
            img_resized = img_resized.astype(np.float32) / 255.0
            # Add batch dimension (B=1, since models expect 4D input)
            img_resized = np.expand_dims(img_resized, 0)

            s = translate_onnx(img_resized, self.session)[0].tolist()
            text = vocab.decode(s)
            return (text, 1.0)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = list(executor.map(recognize_single, img_list))
            
        return results, time.time() - st


class TextDetector:
    def __init__(self, model_dir, device_id: int | None = None):
        pre_process_list = [{
            'DetResizeForTest': {
                'limit_side_len': 960,
                'limit_type': "max",
            }
        }, {
            'NormalizeImage': {
                'std': [0.229, 0.224, 0.225],
                'mean': [0.485, 0.456, 0.406],
                'scale': '1./255.',
                'order': 'hwc'
            }
        }, {
            'ToCHWImage': None
        }, {
            'KeepKeys': {
                'keep_keys': ['image', 'shape']
            }
        }]
        postprocess_params = {"name": "DBPostProcess", "thresh": 0.3, "box_thresh": 0.5, "max_candidates": 1000,
                              "unclip_ratio": 1.5, "use_dilation": False, "score_mode": "fast", "box_type": "quad"}

        self.postprocess_op = build_post_process(postprocess_params)
        self.predictor, self.run_options = load_model(model_dir, 'det', device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

        img_h, img_w = self.input_tensor.shape[2:]
        if isinstance(img_h, str) or isinstance(img_w, str):
            pass
        elif img_h is not None and img_w is not None and img_h > 0 and img_w > 0:
            pre_process_list[0] = {
                'DetResizeForTest': {
                    'image_shape': [img_h, img_w]
                }
            }
        self.preprocess_op = create_operators(pre_process_list)

    def order_points_clockwise(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        tmp = np.delete(pts, [np.argmin(s), np.argmax(s)], axis=0)
        diff = np.diff(np.array(tmp), axis=1)
        rect[1] = tmp[np.argmin(diff)]
        rect[3] = tmp[np.argmax(diff)]
        return rect

    def clip_det_res(self, points, img_height, img_width):
        for pno in range(points.shape[0]):
            points[pno, 0] = min(max(points[pno, 0], 0), img_width - 1)
            points[pno, 1] = min(max(points[pno, 1], 0), img_height - 1)
        return points

    def filter_tag_det_res(self, dt_boxes, image_shape):
        img_height, img_width = image_shape[0:2]
        dt_boxes_new = []
        for box in dt_boxes:
            if isinstance(box, list):
                box = np.array(box)
            box = self.order_points_clockwise(box)
            box = self.clip_det_res(box, img_height, img_width)
            rect_width = int(np.linalg.norm(box[0] - box[1]))
            rect_height = int(np.linalg.norm(box[0] - box[3]))
            if rect_width <= 3 or rect_height <= 3:
                continue
            dt_boxes_new.append(box)
        dt_boxes = np.array(dt_boxes_new)
        return dt_boxes

    def filter_tag_det_res_only_clip(self, dt_boxes, image_shape):
        img_height, img_width = image_shape[0:2]
        dt_boxes_new = []
        for box in dt_boxes:
            if isinstance(box, list):
                box = np.array(box)
            box = self.clip_det_res(box, img_height, img_width)
            dt_boxes_new.append(box)
        dt_boxes = np.array(dt_boxes_new)
        return dt_boxes

    def __call__(self, img):
        ori_im = img.copy()
        data = {'image': img}

        st = time.time()
        data = transform(data, self.preprocess_op)
        if data is None:
            return None, 0
        img, shape_list = data
        img = np.expand_dims(img, axis=0)
        shape_list = np.expand_dims(shape_list, axis=0)
        img = img.copy()
        input_dict = {}
        input_dict[self.input_tensor.name] = img
        outputs = None
        for i in range(100000):
            try:
                outputs = self.predictor.run(None, input_dict, self.run_options)
                break
            except Exception as e:
                if i >= 3:
                    raise e
                time.sleep(5)

        if self.postprocess_op is None:
            raise ValueError("postprocess_op is None")
        if outputs is None:
            raise ValueError("OCR prediction failed to return outputs")
            
        post_result = self.postprocess_op({"maps": outputs[0]}, shape_list)
        dt_boxes = post_result[0]['points'] # type: ignore
        dt_boxes = self.filter_tag_det_res(dt_boxes, ori_im.shape)

        return dt_boxes, time.time() - st


class OCR:
    def __init__(self, model_dir=None):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """
        if not model_dir:
            model_dir = os.path.join(
                        get_project_base_directory(),
                        "onnx")

        if not os.path.exists(os.path.join(model_dir, "det.onnx")):
            try:
                model_dir = snapshot_download(repo_id="InfiniFlow/deepdoc",
                                              local_dir=os.path.join(get_project_base_directory(), "onnx"),
                                              local_dir_use_symlinks=False)
            except Exception as e:
                logging.error(f"Failed to download models: {e}")
                # Nếu model_dir hiện tại không có det.onnx, lỗi sẽ xảy ra ở bước sau

        # Append muti-gpus task to the list
        if PARALLEL_DEVICES is not None and PARALLEL_DEVICES > 0:
            self.text_detector = []
            self.text_recognizer = []
            for device_id in range(PARALLEL_DEVICES):
                self.text_detector.append(TextDetector(model_dir, device_id))
                self.text_recognizer.append(TextRecognizer(model_dir, device_id))
        else:
            self.text_detector = [TextDetector(model_dir, 0)]
            self.text_recognizer = [TextRecognizer(model_dir, 0)]

        self.drop_score = 0.5
        self.crop_image_res_index = 0

    def get_rotate_crop_image(self, img, points):
        '''
        img_height, img_width = img.shape[0:2]
        left = int(np.min(points[:, 0]))
        right = int(np.max(points[:, 0]))
        top = int(np.min(points[:, 1]))
        bottom = int(np.max(points[:, 1]))
        img_crop = img[top:bottom, left:right, :].copy()
        points[:, 0] = points[:, 0] - left
        points[:, 1] = points[:, 1] - top
        '''
        assert len(points) == 4, "shape of points must be 4*2"
        img_crop_width = int(
            max(
                float(np.linalg.norm(points[0] - points[1])),
                float(np.linalg.norm(points[2] - points[3]))))
        img_crop_height = int(
            max(
                float(np.linalg.norm(points[0] - points[3])),
                float(np.linalg.norm(points[1] - points[2]))))
        pts_std = np.array([[0, 0], [img_crop_width, 0],
                            [img_crop_width, img_crop_height],
                            [0, img_crop_height]], dtype="float32")
        M = cv2.getPerspectiveTransform(points.astype(np.float32), pts_std)
        dst_img = cv2.warpPerspective(
            img,
            M, (img_crop_width, img_crop_height),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC)
        dst_img_height, dst_img_width = dst_img.shape[0:2]
        if dst_img_height * 1.0 / dst_img_width >= 1.5:
            dst_img = np.rot90(dst_img)
        return dst_img

    def sorted_boxes(self, dt_boxes):
        """
        Sort text boxes in order from top to bottom, left to right
        args:
            dt_boxes(array):detected text boxes with shape [4, 2]
        return:
            sorted boxes(array) with shape [4, 2]
        """
        num_boxes = dt_boxes.shape[0]
        sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
        _boxes = list(sorted_boxes)

        for i in range(num_boxes - 1):
            for j in range(i, -1, -1):
                if abs(_boxes[j + 1][0][1] - _boxes[j][0][1]) < 10 and \
                        (_boxes[j + 1][0][0] < _boxes[j][0][0]):
                    tmp = _boxes[j]
                    _boxes[j] = _boxes[j + 1]
                    _boxes[j + 1] = tmp
                else:
                    break
        return _boxes

    def detect(self, img, device_id: int | None = None):
        if device_id is None:
            device_id = 0

        time_dict = {'det': 0.0, 'rec': 0.0, 'cls': 0.0, 'all': 0.0}

        if img is None:
            return None, None, time_dict

        start = time.time()
        dt_boxes, _elapse = self.text_detector[device_id](img)
        time_dict['det'] = _elapse

        if dt_boxes is None:
            end = time.time()
            time_dict['all'] = end - start
            return None, None, time_dict

        return zip(self.sorted_boxes(dt_boxes), [
                   ("", 0) for _ in range(len(dt_boxes))])

    def recognize(self, ori_im, box, device_id: int | None = None):
        if device_id is None:
            device_id = 0

        img_crop = self.get_rotate_crop_image(ori_im, box)

        rec_res, elapse = self.text_recognizer[device_id]([img_crop])
        text, score = rec_res[0]
        if score < self.drop_score:
            return ""
        return text

    def recognize_batch(self, img_list, device_id: int | None = None):
        if device_id is None:
            device_id = 0
        rec_res, elapse = self.text_recognizer[device_id](img_list)
        texts = []
        for i in range(len(rec_res)):
            text, score = rec_res[i]
            if score < self.drop_score:
                text = ""
            texts.append(text)
        return texts

    def __call__(self, img, device_id = 0, cls=True):
        time_dict = {'det': 0.0, 'rec': 0.0, 'cls': 0.0, 'all': 0.0}
        if device_id is None:
            device_id = 0

        if img is None:
            return None, None, time_dict

        start = time.time()
        ori_im = img.copy()
        dt_boxes, _elapse = self.text_detector[device_id](img)
        time_dict['det'] = _elapse

        if dt_boxes is None:
            end = time.time()
            time_dict['all'] = end - start
            return None, None, time_dict

        img_crop_list = []
        filtered_dt_boxes = []

        dt_boxes = self.sorted_boxes(dt_boxes)

        for bno in range(len(dt_boxes)):
            tmp_box = copy.deepcopy(dt_boxes[bno])
            img_crop = self.get_rotate_crop_image(ori_im, tmp_box)
            if is_valid_crop(img_crop):
                img_crop_list.append(img_crop)
                filtered_dt_boxes.append(tmp_box)
        dt_boxes = filtered_dt_boxes

        rec_res, _elapse = self.text_recognizer[device_id](img_crop_list)
        time_dict['rec'] = _elapse

        filter_boxes, filter_rec_res = [], []
        for box, rec_result in zip(dt_boxes, rec_res):
            text, score = rec_result
            if score >= self.drop_score:
                filter_boxes.append(box)
                filter_rec_res.append(rec_result)
        end = time.time()
        time_dict['all'] = end - start

        # for bno in range(len(img_crop_list)):
        #    print(f"{bno}, {rec_res[bno]}")

        return list(zip([a.tolist() for a in filter_boxes], filter_rec_res))
