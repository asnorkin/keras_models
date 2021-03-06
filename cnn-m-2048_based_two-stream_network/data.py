import sys
import gc
from numpy.random import seed
seed(7)
import numpy as np
import glob
from utils import get_classes
from sklearn.model_selection import StratifiedShuffleSplit
import cv2
from keras.utils import to_categorical
import scipy.io as sio
from scipy.misc import imresize

def load_inputs(mode, test_subject, parameters, val_index=None):
    data_files_folder = parameters['data_files_folder']
    images_folder = parameters['images_folder']
    of_folder = parameters['of_folder']
    val_size = parameters['percentage_of_train_for_validation']
    classes_file = parameters['classes_file']
    test_evaluation_method = parameters['test_evaluation_method']
    L = parameters['L']
    of_mean = parameters['of_mean']
    image_mean = sio.loadmat(parameters['image_mean'])['image_mean']
    image_shape = (parameters['width'], parameters['height'])
    augment_data = parameters['apply_data_augmentation']
    _width, _height = parameters['dag_resize_shape']
    
    # Load the .txt where train/test partition are saved
    if mode == 'train' or mode == 'val':
        data_file = data_files_folder + '/train_{}.txt'.format(test_subject)
    elif mode == 'test':
        data_file = data_files_folder + '/test_{}.txt'.format(test_subject)
    else:
        print('No valid mode to load data. Options: train, val, test.')
        sys.exit()
        
    # Load video folders and their respective classes to memory
    folders, labels = [], []
    class_dict = get_classes(classes_file)
    with open(data_file, 'r') as f:
        content = f.readlines()
        for i in range(len(content)):
            folder, label = content[i].strip().split(' ')
            folders.append(folder)
            class_name = folder[folder.find('/')+1:folder.rfind('/')]
            labels.append(class_dict[class_name])
       
    # Stratify the dataset in train to get a validation partition:
    # i.e., get a subset of the training set with the same class distsribution
    if mode == 'train':
        sss = StratifiedShuffleSplit(
            n_splits=1, test_size=val_size, random_state=0
        )
        indices = sss.split(folders, labels)
        val_index = indices.next()[1]
    
    X, Y = [], []
    for i in range(len(folders)):
        folder = folders[i]
        class_name = folder[folder.find('/')+1:folder.rfind('/')]
        # Only include the elements with index inside val_index
        # for the validation set
        if mode == 'val':
            if i in val_index:
                X.append(folder)
                Y.append(int(labels[i]))
        # Do not include elements of the validation set in the training set
        elif mode == 'train':
            if not i in val_index:
                X.append(folder)
                Y.append(int(labels[i]))
        elif mode == 'test':
            X.append(folder)
            Y.append(int(labels[i]))
    del folders, labels
    gc.collect()
   
    folders_in_class = dict()
    class_of_folder = dict()        
    for folder, label in zip(X, Y):
        temp = folder[:folder.rfind('/')]
        class_name = temp[temp.rfind('/')+1:]

        # Store the folders by class
        if not folders_in_class.has_key(class_name):  
            folders_in_class[class_name] = []
        folders_in_class[class_name].append(folder)
        class_of_folder[folder] = label
        
    perm = np.random.permutation(len(folders_in_class.keys()))
    (batches_images, batches_stacks, batches_labels,
     inputs_per_video, video_names) = [], [], [], [],[]
    #batch_labels_video = []
    #video_durations = []
    nb_videos = 0
    
    # p contains a class index, randomized by perm
    for p in np.asarray(folders_in_class.keys())[list(perm)]:         
        folders = folders_in_class[p]
        for element in folders:  
            video_names.append(element)
            inputs_per_video.append(nb_videos)
            
            # Load images:
            frames = glob.glob(images_folder + element + '/frame*')
            # In case of less than L images, replicate them
            if len(frames) < L:
                reps = int(L/len(frames))
                temp = frames
                frames = []
                for i in range(len(temp)):
                    for _ in xrange(reps):
                        frames.append(temp[i])
            temp = []
            indices = []
            if test_evaluation_method != 0:   
                for i in xrange(len(frames)):        
                    img = cv2.imread(frames[i]) - image_mean
                    # subtract the image mean (used in the pre-training)
                    if mode == 'train' and augment_data: 
                        img = imresize(img, (_width, _height), interp='bilinear') 
                    temp.append(img)
            else:
                indices = list(np.asarray(np.linspace(0,len(frames)-1,25),dtype=np.int))
                for i in indices:   
                    img = cv2.imread(frames[i]) - image_mean
                    img = imresize(img, (_width, _height), interp='bilinear') 
                    temp.append(img)
            batches_images.append(temp)                    
            
            # Load optical flow and stack L horizontal and vertical images
            x_frames = glob.glob(of_folder + element + '/flow_x*')
            y_frames = glob.glob(of_folder + element + '/flow_y*')
            if len(frames) < L:
                reps = int(L/len(x_frames))
                temp_x, temp_y = x_frames, y_frames
                x_frames, y_frames = [], []
                for i in range(len(temp_x)):
                    for _ in xrange(reps):
                        x_frames.append(temp_x[i])
                        y_frames.append(temp_y[i])
                        
            rest = len(x_frames) % L
            add = 0
            # In case of spare optical flow images, add one more stack
            # taking the last L images (there is some overlap with the
            # previous stack)
            if rest > 0:
                add = 1
            temp = []
            if test_evaluation_method != 0: 
                for r in xrange((len(x_frames) // L) + add):        
                    low, high = r*L, (r+1)*L
                    if high > len(x_frames):
                        low, high = -L, len(x_frames)
                    i = 0
                    if mode == 'train' and augment_data:
                        flow = np.zeros(shape=(_width, _height, 2*L,),
                                        dtype=np.float32)
                    else:
                        flow = np.zeros(shape=image_shape + (2*L,),
                                        dtype=np.float32)
                    for flow_x_file, flow_y_file in zip(
                            x_frames[low:high],y_frames[low:high]):
                        img_x = cv2.imread(flow_x_file, cv2.IMREAD_GRAYSCALE)
                        img_y = cv2.imread(flow_y_file, cv2.IMREAD_GRAYSCALE)
                        # Resize to larger size in order to crop them later
                        if mode == 'train' and augment_data: 
                            img_x = imresize(img_x, (_width, _height),
                                             interp='bilinear') 
                            img_y = imresize(img_y, (_width, _height),
                                             interp='bilinear') 
                        flow[:,:,2*i] = img_x
                        flow[:,:,2*i+1] = img_y
                        i += 1
                    # Subtract the Optical Flow mean (used in the pre-training)
                    temp.append(flow - of_mean) 
                    nb_videos += 1   
                assert len(temp) == ((len(x_frames) // L)+add)
            else:
                for i in indices: 
                    flow = np.zeros(shape=(_width, _height, 2*L,),
                                        dtype=np.float32)
                    n = 0
                    for j in range(i-5,i+4):
                        k = max(min(j,0),len(x_frames)-1)
                        img_x = cv2.imread(x_frames[k], cv2.IMREAD_GRAYSCALE)
                        img_y = cv2.imread(y_frames[k], cv2.IMREAD_GRAYSCALE)
                        img_x = imresize(img_x, (_width, _height),
                                             interp='bilinear') 
                        img_y = imresize(img_y, (_width, _height),
                                         interp='bilinear') 
                        flow[:,:,2*n] = img_x
                        flow[:,:,2*n+1] = img_y
                        n += 1
                    temp.append(flow - of_mean)
                    nb_videos += 1   
            batches_stacks.append(temp)
            batches_labels.append(class_of_folder[element])
    if mode != 'test':
        return {'images': batches_images, 'stacks': batches_stacks, 
                'labels': batches_labels, 'inputs_per_video': inputs_per_video,
                'val_index': val_index, 'video_names': video_names}
    else:
        return {'images': batches_images, 'stacks': batches_stacks, 
                'labels': batches_labels, 'inputs': nb_videos}
    
def load_train_val_image_dataset(parameters, test_subject):
    training_set = load_inputs('train', test_subject, parameters)
    validation_set = load_inputs(
        'val', test_subject, parameters, val_index=training_set['val_index']
    )
    assert len(training_set['images']) == len(training_set['labels']), (
        'Number of inputs should be equal to the number of labels in '
        'training set but found: {} inputs and {} labels'.format(
            len(training_set['images']), len(training_set['labels'])
        )
    )
    assert len(validation_set['images']) == len(validation_set['labels']), (
        'Number of inputs should be equal to the number of labels in '
        'validation set but found: {} inputs and {} labels'.format(
        len(validation_set['images']), len(validation_set['labels']))
    )
    return training_set, validation_set
    
def load_test_image_dataset(parameters, test_subject):
    test_set = load_inputs('test', test_subject, parameters)
    assert len(test_set['images']) == len(test_set['labels']), (
        'Number of inputs should be equal to the number of labels in '
        'test set but found: {} inputs and {} labels'.format(
        len(test_set['images']), len(test_set['labels']))
    )   
    return test_set
    
# This function was done by @rubensancor
def load_one_test_image(parameters, test_subject):
    data_files_folder = parameters['data_files_folder']
    images_folder = parameters['images_folder']
    of_folder = parameters['of_folder']
    L = parameters['L']
    of_mean = parameters['of_mean']
    image_mean = sio.loadmat(parameters['image_mean'])['image_mean']
    image_shape = (parameters['width'], parameters['height'])
    
    data_file = data_files_folder + '/test_{}.txt'.format(test_subject)
    with open(data_file, "r") as f:
        content = f.readlines()
        path = content[0]
        folder, label = path.strip().split(' ')
    
    img = cv2.imread(glob.glob(images_folder + folder + "/frame*")[5]) - image_mean
    
    of_path_x = glob.glob(of_folder + folder + "/flow_x*")[:10]
    of_path_y = glob.glob(of_folder + folder + "/flow_y*")[:10]
    i = 0
    flow = np.zeros(shape=image_shape + (2*L,), dtype=np.float32)
    for flow_x_file, flow_y_file in zip( of_path_x, of_path_y):
        img_x = cv2.imread(flow_x_file, cv2.IMREAD_GRAYSCALE)
        img_y = cv2.imread(flow_y_file, cv2.IMREAD_GRAYSCALE)
        flow[:,:,2*i] = img_x
        flow[:,:,2*i+1] = img_y
        i += 1
    of = flow - of_mean
    
    return img, of, label

def batch_generator(mode, parameters, dataset):
    test_evaluation_method = parameters['test_evaluation_method']
    nb_classes = parameters['nb_classes']
    L = parameters['L']
    batch_size = parameters['batch_size']
    augment_data = parameters['apply_data_augmentation']
    width, height = parameters['width'], parameters['height']
    _width, _height = parameters['dag_resize_shape']
    width_dif, height_dif = _width-width, _height-height
    evens = [n for n in range(20) if n % 2 == 0]
    
    while True:
        if mode == 'test':
            nb_inputs = dataset['inputs']
            # TEST METHOD 1: Get 25 images + optical flow stacks,
            # crop 4 corneres and center and get their mirrored version.
            # Majority voting with the 10*25 inputs obtained to classify the 
            # video
            if test_evaluation_method == 0:
                for i in xrange(len(dataset['images'])):
                    batch_images, batch_ofs = [], []
                    for j in range(len(dataset['images'][i])):
                        crops = [[0,width,0,height],
                                 [0,width,height_dif,height_dif+height],
                                 [width_dif, width_dif+width,
                                  height_dif,height_dif+height],
                                 [width_dif,width_dif+width,0,height],
                                 [width_dif/2,width_dif/2+width,
                                  height_dif/2,height_dif/2+height]
                                ]
                        for crop in crops:
                            img = dataset['images'][i][j][
                                                crop[0]:crop[1], crop[2]:crop[3],:
                                             ]
                            stack = dataset['stacks'][i][j][
                                                crop[0]:crop[1], crop[2]:crop[3],:
                                            ]
                            for mirroring in [False, True]:
                                if mirroring:
                                    img = np.fliplr(img)
                                    stack[...,evens] = 255 - stack[...,evens]
                                batch_images.append(img)
                                batch_ofs.append(stack)
    
                    yield (np.asarray(batch_images),
                           np.asarray(batch_ofs), 
                           np.asarray(
                               to_categorical(dataset['labels'][i], nb_classes)
                               )
                          )
            # TEST METHOD 2: Get all the inputs of the video and do
            # majority voting with all of them
            elif test_evaluation_method == 1:
                for i in xrange(len(dataset['stacks'])):
                    batch_images, batch_ofs = [], []
                    for j in range(len(dataset['stacks'][i])):                        
                        if j*L+L > len(dataset['images'][i]):
                            pos_image = -(L/2)
                        else:
                            pos_image = j*L + L/2 
                        #print(len(dataset['stacks'][i]), len(dataset['images'][i]),
                        #      j, pos_image)
                        batch_images.append(dataset['images'][i][pos_image])
                        batch_ofs.append(dataset['stacks'][i][j])
                    yield (np.asarray(batch_images),
                           np.asarray(batch_ofs), 
                           np.asarray(
                               to_categorical(dataset['labels'][i], nb_classes)
                               )
                          )
        # Train and val
        else:
            nb_inputs = dataset['inputs_per_video'][-1]
            perm = np.random.permutation(nb_inputs)
            batch_images, batch_ofs, batch_labels = [], [], []
            for i in xrange(nb_inputs): 
                pos = np.searchsorted(
                    dataset['inputs_per_video'], perm[i], side='left'
                )
                if dataset['inputs_per_video'][pos] > perm[i]:
                    pos -= 1
                pos_stack = perm[i]-dataset['inputs_per_video'][pos]
                
                if pos_stack*L+L >= len(dataset['images'][pos]):
                    if mode == 'train':
                        inner_pos = (len(dataset['images'][pos]) - 1 - 
                                    np.random.randint(0, L))
                    else:
                        inner_pos = len(dataset['images'][pos]) - 1 - 5
                else:
                    if mode == 'train':
                        inner_pos = np.random.randint(pos_stack*L,pos_stack*L+L)
                    else:
                        inner_pos = pos_stack*L + L/2 
                        
                # Data augmentation
                if mode == 'train' and augment_data:
                    # Random Cropping
                    dx = np.random.randint(0, _width-width)
                    dy = np.random.randint(0, _height-height)
                    img = dataset['images'][pos][inner_pos][
                                    dx:dx+width, dy:dy+height
                                ]
                    stack = dataset['stacks'][pos][pos_stack][
                                        dx:dx+width, dy:dy+height,:
                                    ]
                    # Random Mirroring
                    rand = np.random.rand(1) 
                    if rand > 0.5:
                        img = np.fliplr(img)
                        stack[...,evens] = 255 - stack[...,evens]
                    batch_images.append(img)
                    batch_ofs.append(stack)
                    batch_labels.append(
                        to_categorical(dataset['labels'][pos], nb_classes)
                    )
                else:
                    batch_images.append(dataset['images'][pos][inner_pos])
                    batch_ofs.append(dataset['stacks'][pos][pos_stack])
                    batch_labels.append(
                        to_categorical(dataset['labels'][pos], nb_classes)
                    )
                if len(batch_images) == batch_size:
                    yield (np.asarray(batch_images), np.asarray(batch_ofs),
                           np.asarray(batch_labels))
                    batch_images, batch_ofs, batch_labels = [], [], []
            if mode == 'val' or mode == 'test':
                if len(batch_images) > 0:
                    yield (np.asarray(batch_images), np.asarray(batch_ofs),
                           np.asarray(batch_labels))
                    batch_images, batch_ofs, batch_labels = [], [], []
            elif mode == 'train' and nb_inputs % batch_size > 0:
                indices = np.random.choice(
                    range(nb_inputs), nb_inputs % batch_size
                )
                for i in indices:
                    pos = np.searchsorted(
                        dataset['inputs_per_video'], i, side='left'
                    )
                    if dataset['inputs_per_video'][pos] > i:
                        pos -= 1
                    pos_stack = i-dataset['inputs_per_video'][pos]
                    if pos_stack*L+L >= len(dataset['images'][pos]):
                        if mode == 'train':
                            inner_pos = (len(dataset['images'][pos]) - 1 -
                                        np.random.randint(0, L))
                        else:
                            inner_pos = len(dataset['images'][pos]) - 1 - 5
                    else:
                        if mode == 'train':
                            inner_pos = np.random.randint(
                                pos_stack*L,pos_stack*L+L
                            )
                        else:
                            inner_pos = pos_stack*L + L/2 
                            
                    # Data augmentation
                    if mode == 'train' and augment_data:
                        # Random Cropping
                        dx = np.random.randint(0, _width-width)
                        dy = np.random.randint(0, _height-height)
                        img = dataset['images'][pos][inner_pos][
                                        dx:dx+width, dy:dy+height
                                    ]
                        stack = dataset['stacks'][pos][pos_stack][
                                            dx:dx+width, dy:dy+height,:
                                        ]
                        # Random Mirroring
                        rand = np.random.rand(1) 
                        if rand > 0.5:
                            img = np.fliplr(img)
                            stack[...,evens] = 255 - stack[...,evens]
                            
                        batch_images.append(img)
                        batch_ofs.append(stack)
                        batch_labels.append(
                            to_categorical(dataset['labels'][pos], nb_classes)
                        )
                    
                    else:
                        batch_images.append(dataset['images'][pos][inner_pos])
                        batch_ofs.append(dataset['stacks'][pos][pos_stack])
                        batch_labels.append(
                            to_categorical(dataset['labels'][pos], nb_classes)
                        )
                    if len(batch_images) == batch_size:
                        yield (np.asarray(batch_images), np.asarray(batch_ofs),
                               np.asarray(batch_labels))
                        batch_images, batch_ofs, batch_labels = [], [], []
