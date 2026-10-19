# -*- coding: utf-8 -*-
"""
Авто-поворот новой коробки.

С TensorFlow: нейросеть авторов SUSTechPOINTS (обучена на машинах и пешеходах) по 512 точкам
объекта предсказывает угол с шагом 3 градуса.
Без TensorFlow (или при SUSTECH_NO_TF=1): угол длинной стороны минимального прямоугольника,
описанного вокруг точек объекта в плане. Для стен, стеллажей и труб это и есть нужный поворот;
для техники "перед" таким способом не определить - его правит разметчик.
"""
import os
import glob
import math
import json
import numpy as np
from . import util

RESAMPLE_NUM = 10
NUM_POINT = 512
model_file = "./algos/models/deep_annotation_inference.h5"

rotation_model = None
tf = None
if os.environ.get("SUSTECH_NO_TF") == "1":
    print("авто-поворот: нейросеть отключена (SUSTECH_NO_TF=1), поворот по геометрии точек")
else:
    try:
        import tensorflow as tf
        util.config_gpu()
        rotation_model = tf.keras.models.load_model(model_file)
        print("авто-поворот: нейросеть загружена")
    except Exception as e:
        rotation_model = None
        print("авто-поворот: TensorFlow или модель недоступны, поворот по геометрии точек. Причина:", str(e)[:200])


def sample_one_obj(points, num):
    if points.shape[0] < NUM_POINT:
        return np.concatenate([points, np.zeros((NUM_POINT - points.shape[0], 3), dtype=np.float32)], axis=0)
    else:
        idx = np.arange(points.shape[0])
        np.random.shuffle(idx)
        return points[idx[0:num]]


def yaw_from_points(points):
    """
    Угол (рад) объекта в плане без нейросети: L-shape fitting по критерию прижатости
    (Zhang et al., 2017). Перебираем угол 0..90 градусов, для каждого считаем, насколько точки
    прижаты к сторонам описанного прямоугольника, берём лучший и уточняем до 0.1 градуса.
    Возвращаем направление длинной стороны.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if p.shape[0] < 3:
        return 0.0
    above = p[p[:, 2] > p[:, 2].min() + 0.3]        # убираем слой земли, если он попал в выделение
    if above.shape[0] >= 10:
        p = above
    xy = p[:, :2]
    if xy.shape[0] > 1500:
        xy = xy[np.random.default_rng(0).choice(xy.shape[0], 1500, replace=False)]
    x, y = xy[:, 0], xy[:, 1]
    d0 = 0.05                                          # ближе 5 см считаем "на стороне"

    def closeness(theta):
        c, s = math.cos(theta), math.sin(theta)
        u = x * c + y * s
        v = -x * s + y * c
        d1 = np.minimum(u.max() - u, u - u.min())
        d2 = np.minimum(v.max() - v, v - v.min())
        d = np.maximum(np.minimum(d1, d2), d0)
        return float(np.sum(1.0 / d))

    best_t, best_s = 0.0, -1.0
    for deg in range(0, 90):
        t = math.radians(deg)
        sc = closeness(t)
        if sc > best_s:
            best_t, best_s = t, sc
    for dd in np.arange(-1.0, 1.01, 0.1):               # уточнение вокруг лучшего
        t = best_t + math.radians(dd)
        sc = closeness(t)
        if sc > best_s:
            best_t, best_s = t, sc
    c, s = math.cos(best_t), math.sin(best_t)
    u = x * c + y * s
    v = -x * s + y * c
    yaw = best_t if (u.max() - u.min()) >= (v.max() - v.min()) else best_t + math.pi / 2
    return float(math.atan2(math.sin(yaw), math.cos(yaw)))


def predict_yaw(points):
    points = np.array(points, dtype=np.float32).reshape((-1, 3))
    if rotation_model is None:
        return [0, 0, yaw_from_points(points)]
    input_data = np.stack([x for x in map(lambda x: sample_one_obj(points, NUM_POINT), range(RESAMPLE_NUM))], axis=0)
    pred_val = rotation_model.predict(input_data, verbose=0)
    pred_cls = np.argmax(pred_val, axis=-1)
    ret = (pred_cls[0] * 3 + 1.5) * np.pi / 180.
    return [0, 0, float(ret)]


if rotation_model is not None:
    predict_yaw(np.random.random([1000, 3]))        # прогрев модели


if False:
    # weights_path = "../DeepAnnotate/da_rp_weights.h5"
    # #filter_model = tf.keras.filter_models.load_filter_model(filter_model_path)

    # filter_model = M.get_filter_model_rp_discrimination(common.NUM_POINT, 2, False)

    # # filter_model.compile(optimizer=tf.keras.optimizers.Adam(0.0001), 
    # #             loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
    # #             metrics=[tf.keras.metrics.sparse_categorical_accuracy, tf.keras.metrics.SparseTopKCategoricalAccuracy(k=2)])
    # #filter_model.summary()

    # filter_model.load_weights(weights_path)
    # filter_model.summary()

    use_env = False
    if use_env:
        filter_model_file = './algos/models/deepannotate_rp_discrimination_env.h5'  #"./deepannotate_rp_discrimination.back.h5"
    else:
        filter_model_file = './algos/models/deepannotate_rp_discrimination_obj_xyzi.h5'  #"./deepannotate_rp_discrimination.back.h5"
    filter_model = tf.keras.models.load_model(filter_model_file)
    filter_model.summary()



    # rotation_model_file = "../SUSTechPoints-be/algos/models/deep_annotation_inference.h5"
    # rotation_model = tf.keras.models.load_model(rotation_model_file)
    # rotation_model.summary()

    # #from rotation import  model as rotation_model

    # #NUM_POINT = 512

    def cluster_points(pcdfile):
        def pre_cluster_pcd(file, output_folder):
            pre_cluster_exe = "/home/lie/code/pcltest/build/cluster"    
            cmd = "{} {} {}".format(pre_cluster_exe, file, output_folder)
            #print(cmd)
            os.system(cmd)

        temp_output_folder = "./temppcd"
        if os.path.exists(temp_output_folder):
            os.system("rm {}/*".format(temp_output_folder))
        else:
            os.mkdir(temp_output_folder)

        pre_cluster_pcd(pcdfile, temp_output_folder)

        obj_files = glob.glob(temp_output_folder+"/*-obj.bin")
        env_files = glob.glob(temp_output_folder+"/*-env.bin")
        obj_files.sort()
        env_files.sort()
        
        ## note these clusters are already sorted by points number
        objs = [np.fromfile(c, dtype=np.float32).reshape(-1, 4) for c in obj_files]
        envs = [np.fromfile(c, dtype=np.float32).reshape(-1, 4) for c in env_files]
        clusters = list(zip(objs, envs))
        return clusters

    def euler_angle_to_rotate_matrix(eu, t):
        theta = eu
        #Calculate rotation about x axis
        R_x = np.array([
            [1,       0,              0],
            [0,       math.cos(theta[0]),   -math.sin(theta[0])],
            [0,       math.sin(theta[0]),   math.cos(theta[0])]
        ])

        #Calculate rotation about y axis
        R_y = np.array([
            [math.cos(theta[1]),      0,      math.sin(theta[1])],
            [0,                       1,      0],
            [-math.sin(theta[1]),     0,      math.cos(theta[1])]
        ])

        #Calculate rotation about z axis
        R_z = np.array([
            [math.cos(theta[2]),    -math.sin(theta[2]),      0],
            [math.sin(theta[2]),    math.cos(theta[2]),       0],
            [0,               0,                  1]])

        R = np.matmul(R_x, np.matmul(R_y, R_z))

        t = t.reshape([-1,1])
        R = np.concatenate([R,t], axis=-1)
        R = np.concatenate([R, np.array([0,0,0,1]).reshape([1,-1])], axis=0)
        return R


    def sample_one_obj(points, num):
        centroid = list(np.mean(points[:,:3], axis=0))  # intensity

        if points.shape[1] > 3:
            centroid = np.append(centroid, np.zeros(points.shape[1]-3))
            print(centroid)
            centroid.reshape(1,-1)
        points = points - centroid

        # padding or sample
        if points.shape[0]>num:
            idx = np.arange(points.shape[0])
            np.random.shuffle(idx)
            points =  points[idx[0:num]]
        else:
            sample_idx = np.random.randint(0, high = points.shape[0], size=num - points.shape[0])
            padding = points[sample_idx]
            points = np.concatenate([points, padding], axis=0)

        print("input shape", points.shape)
        return points[:,:3]

    def filter_nearby_objects(clusters):
        def nearby(c): # c is a pair
            center = np.mean(c,axis=0)
            return np.sum((center*center)[0:2]) < 70*70

        ind = [nearby(c[0]) for c in clusters]
        return np.array(clusters)[ind]


    # # return true/false list
    def filter_candidate_objects(clusters):

        ## all clusters stacked into a batch
        
        objidx = 1 if use_env else 0
        input_cluster_points = np.stack([sample_one_obj(p[objidx], NUM_POINT) for p in clusters], axis=0) # use env to do filtering

        pred_val = filter_model.predict(input_cluster_points)
        #print(pred_val)
        prob = np.exp(pred_val)/np.sum(np.exp(pred_val),axis=1,keepdims=True)

        #print(prob)
        #pred_cls = np.argmax(prob, axis=1)
        pred_cls = prob[:,1]>0.5
        return pred_cls

    def decide_obj_rotation(objs):
        input_data = np.stack([sample_one_obj(o, NUM_POINT) for o in objs], axis=0)
        pred_val = rotation_model.predict(input_data)
        pred_cls = np.argmax(pred_val, axis=-1)
        
        ret = (pred_cls*3+1.5)*np.pi/180.0  #only z-axis rotation is predicted
        
        return ret

    def calculate_box_dimension(objs, rotation):

        def calc_one_box(obj, rot):
            #print(obj.shape, rot)
            rot = np.array([0,0,rot])
            centroid = np.mean(obj, axis=0)
            obj = obj - centroid
            
            trans_mat = euler_angle_to_rotate_matrix(rot, np.zeros(3))[:3,:3]
            relative_position = np.matmul(obj, trans_mat)

            pmin = np.min(relative_position, axis=0)        
            pmax = np.max(relative_position, axis=0)
            pmin[2]  = pmin[2] - 0.2 # remember 0.2 was removed, as ground

            box_dim = pmax-pmin
            box_center_delta = box_dim/2 + pmin
            #center delta shoulb be translated to global coord
            box_center_delta = np.matmul(trans_mat, box_center_delta)

            box_center = box_center_delta + centroid
            
            return np.stack([box_center, box_dim, rot],axis=0)

                
        return [calc_one_box(obj, rot) for obj,rot in zip(objs, rotation)]



    ## main func
    def pre_annotate(pcdfile):
        clusters = cluster_points(pcdfile)

        clusters = filter_nearby_objects(clusters)
        cand_ind = filter_candidate_objects(clusters)

        # positive_files = np.array(cluster_files)[cand_ind]
        # positive_files = [x for x in map(lambda f: f.replace(".bin",".pcd"), list(positive_files))]

        # outstr = ""
        # for f in positive_files:
        #     outstr = outstr + " " + f

        # print(outstr)


        # calculate box
        cand_clusters = np.array(clusters)[cand_ind]

        # only objs is needed from now on
        cand_clusters = [x[0][:,:3] for x in cand_clusters] 
        cand_rotation = decide_obj_rotation(cand_clusters)

        # print(cand_rotation)
        boxes = calculate_box_dimension(cand_clusters, cand_rotation)
        #print(boxes)
        return boxes


    def translate_np_to_json(boxes):
        def trans_one_box(box):
            return {
                'obj_type': 'Unknown',
                'psr': {
                    'position': {
                        'x': box[0,0],
                        'y': box[0,1],
                        'z': box[0,2],
                    },
                    'scale': {
                        'x': box[1,0],
                        'y': box[1,1],
                        'z': box[1,2],
                    },
                    'rotation': {
                        'x': box[2,0],
                        'y': box[2,1],
                        'z': box[2,2],
                    }
                },
                'obj_id': '',            
            }
        
    #     return [trans_one_box(b) for b in boxes]

    def annotate_file(input, output=None):
        boxes = pre_annotate(input)
        boxes_json = translate_np_to_json(boxes)
        
        if output:
            with open(output, 'w') as f:
                json.dump(boxes_json, f)

        return boxes_json

# if __name__ == "__main__":
#     #root_folder = "/home/lie/fast/code/SUSTechPoints-be/data/sustechscapes-mini-dataset-test"
#     root_folder = "/home/lie/fast/code/SUSTechPoints-be/data/2020-07-12-15-36-24"
#     files = os.listdir(root_folder + "/lidar")
#     files.sort()
#     for pcdfile in files:
#         print(pcdfile)
#         jsonfile = pcdfile.replace(".pcd",".json")

#         annotate_file(root_folder + "/lidar/" + pcdfile, root_folder + "/label/" + jsonfile)