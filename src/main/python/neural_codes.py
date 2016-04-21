import os
import numpy as np
import caffe
from extra_functions import pairwise_distance

caffe_root = os.path.join(os.path.expanduser('~'), 'caffe/')


def caffe_image_transformer(net):
    assert type(net) is caffe.Net
    mean = np.load(caffe_root + 'python/caffe/imagenet/ilsvrc_2012_mean.npy').transpose((1, 2, 0))
    transformer = caffe.io.Transformer({'data': net.blobs['data'].data.shape})
    transformer.set_transpose('data', (2, 0, 1))  # move image channels to outermost dimension
    transformer.set_mean('data', mean)  # subtract the dataset-mean value in each channel
    transformer.set_raw_scale('data', 255)  # rescale from [0, 1] to [0, 255]
    transformer.set_channel_swap('data', (2, 1, 0))  # swap channels from RGB to BGR
    return transformer


def nc_patch_codes(imbase_files, net, patch_level, layer_name, gpu_mode):
    assert type(imbase_files) is list
    assert type(net) is caffe.Net
    assert type(patch_level) is int
    assert type(layer_name) is str
    assert type(gpu_mode) is bool

    patches_per_image = patch_level ** 2
    n_images = len(imbase_files)
    total_patches_num = n_images * patches_per_image
    neural_codes = np.zeros([net.params[layer_name][1].data.shape[0], total_patches_num], dtype=np.float32)
    n_channels = net.blobs['data'].data.shape[1]
    net_input_height = net.blobs['data'].data.shape[2]
    net_input_width = net.blobs['data'].data.shape[3]
    patch_array = np.empty([n_channels, net_input_height, net_input_width, total_patches_num], dtype=np.float32)  # first 3 coordinates, e.g. (3, 227, 227)
    transformer = caffe_image_transformer(net)
    cur_index = 0
    for image_index in xrange(n_images):
        file_name = imbase_files[image_index]
        im = caffe.io.load_image(file_name)  # на будущее - в skimage есть также imread_collection -- чтение блока картинок
        im_height = im.size[0]
        im_width = im.size[1]
        for patch_ver_index in xrange(1, patch_level + 1):
            ver_lower_bound = round((patch_ver_index - 1) / (patch_level + 1) * im_height)
            ver_upper_bound = round((patch_ver_index + 1) / (patch_level + 1) * im_height)
            for patch_hor_index in xrange(1, patch_level + 1):
                hor_lower_bound = round((patch_hor_index - 1) / (patch_level + 1) * im_width)
                hor_upper_bound = round((patch_hor_index + 1) / (patch_level + 1) * im_width)
                patch = im[ver_lower_bound:ver_upper_bound, hor_lower_bound:hor_upper_bound, :]
                patch_array[:, :, :, cur_index] = transformer.preprocess('data', patch)
                cur_index += 1

    for patch_index in xrange(total_patches_num):
        net.blobs['data'].data[...] = patch_array[patch_index]
        cnn_output = net.blobs[layer_name].data[0]
        neural_codes[:, patch_index] = cnn_output.copy()

    return neural_codes


def nc_compute(imbase_path, imbase_files, net, nc_full_name, layer_name, patch_level, gpu_mode):
    assert type(imbase_path) is str
    assert type(imbase_files) is list
    assert type(net) is caffe.Net
    assert type(nc_full_name) is str
    assert type(layer_name) is str
    assert type(patch_level) is int
    assert type(gpu_mode) is bool

    n_images = len(imbase_files)
    for image_index in xrange(n_images):
        imbase_files[image_index] = os.path.join(imbase_path, imbase_files[image_index])

    rest = n_images
    while rest > 0:
        used_num = 10  # Здесь должна быть более продвинутая функция по вычислению количества свободного места, но пока будем брать константу
        head = n_images - rest
        tail = n_images - rest + used_num
        rest -= used_num
        neural_codes_array = nc_patch_codes(imbase_files[head:tail], net, patch_level, layer_name, gpu_mode)
        neural_codes_array.tofile(nc_full_name)  # Чтение -- через np.fromfile(), также надо понять в каком порядке идет запись -- строчном или столбцовом


def nc_find_nearest(input_image_file, imbase_path, imbase_files, net, layer_name, neural_codes_query, max_patch_level_ref, max_patch_level_query, gpu_mode):
    assert type(input_image_file) is np.ndarray
    assert type(imbase_path) is str
    assert type(imbase_files) is list
    assert type(net) is caffe.Net
    assert type(layer_name) is str
    assert type(neural_codes_query) is np.ndarray
    assert type(max_patch_level_ref) is int
    assert type(max_patch_level_query) is int
    assert type(gpu_mode) is bool

    n_images = len(imbase_files)
    num_patches_per_image_ref = np.square(np.arange(1, max_patch_level_ref).sum())
    num_patches_per_image_query = np.square(np.arange(1, max_patch_level_query).sum())
    layer_output_size = net.params[layer_name][1].data.shape[0]
    neural_codes_ref = np.empty([layer_output_size, np.arange(1, max_patch_level_ref).sum()], dtype=np.float32)
    for patch_level_ref in xrange(1, max_patch_level_ref):
        head = np.square(np.arange(0, max_patch_level_ref - 1).sum())
        tail = np.square(np.arange(1, max_patch_level_ref).sum())
        neural_codes_ref[head:tail, :] = nc_patch_codes(list(input_image_file), net, patch_level_ref, layer_name, gpu_mode)
    pairwise_dist_table = np.zeros([num_patches_per_image_ref, n_images * num_patches_per_image_query], dtype=np.float32)
    # Здесь нужно будет добавить PCA
    total_cols_num = neural_codes_query.shape[1]
    # Для более продвинутого алгоритма будем использовать эту строчку: num_bytes_per_patch_nc = np.float32().nbytes * neural_codes_ref.shape[0]
    rest = total_cols_num
    while rest > 0:
        used_num = 10  # Здесь должна быть более продвинутая функция по вычислению количества свободного места, но пока будем брать константу
        head = total_cols_num - rest
        tail = total_cols_num - rest + used_num
        pairwise_dist_table[head:tail, :] = pairwise_distance(neural_codes_ref, neural_codes_query[head:tail, :])
        rest -= used_num
    neural_codes_distances = np.ravel(np.min(pairwise_dist_table.reshape([num_patches_per_image_ref, max_patch_level_query, n_images]), axis=1).mean(axis=0))
    sorted_indices = neural_codes_distances.argsort()
    n_nearest = min(n_images, 10)