#!/usr/bin/env python

import datetime
import json
import math
import numpy as np
import os
from sklearn import metrics
import tensorflow as tf
from tensorflow.contrib.session_bundle import exporter
from tensorflow.python.ops import rnn, rnn_cell

# Define hyperparameters
flags = tf.app.flags
FLAGS = flags.FLAGS
flags.DEFINE_string("train_tfrecords_path", "data/cancer_train.csv.tfrecords",
                    "Path of train TFRecords files")
flags.DEFINE_string("validate_tfrecords_path",
                    "data/cancer_test.csv.tfrecords",
                    "Path of validate TFRecords files")
flags.DEFINE_integer("feature_size", 9, "Number of feature size")
flags.DEFINE_integer("label_size", 2, "Number of label size")
flags.DEFINE_float("learning_rate", 0.01, "Initial learning rate")
flags.DEFINE_integer("epoch_number", None, "Number of epochs to run trainer")
flags.DEFINE_integer("batch_size", 1024,
                     "indicates batch size in a single gpu, default is 1024")
flags.DEFINE_integer("validate_batch_size", 1024,
                     "indicates batch size in a single gpu, default is 1024")
flags.DEFINE_integer("thread_number", 1, "Number of thread to read data")
flags.DEFINE_integer("min_after_dequeue", 100,
                     "indicates min_after_dequeue of shuffle queue")
flags.DEFINE_string("checkpoint_path", "./checkpoint/",
                    "indicates the checkpoint dirctory")
flags.DEFINE_string("output_path", "./tensorboard/",
                    "indicates training output")
flags.DEFINE_string("model", "dnn",
                    "Model to train, option model: dnn, lr, wide_and_deep")
flags.DEFINE_boolean("enable_bn", False, "Enable batch normalization or not")
flags.DEFINE_float("bn_epsilon", 0.001, "The epsilon of batch normalization")
flags.DEFINE_boolean("enable_dropout", False, "Enable dropout or not")
flags.DEFINE_float("dropout_keep_prob", 0.5, "The dropout keep prob")
flags.DEFINE_boolean("enable_lr_decay", False, "Enable learning rate decay")
flags.DEFINE_float("lr_decay_rate", 0.96, "Learning rate decay rate")
flags.DEFINE_string("optimizer", "adagrad", "optimizer to train")
flags.DEFINE_integer("steps_to_validate", 10,
                     "Steps to validate and print loss")
flags.DEFINE_string("mode", "train", "Option mode: train, export, inference")
flags.DEFINE_string("model_path", "./model/", "indicates training output")
flags.DEFINE_integer("export_version", 1, "Version number of the model.")


def main():
  # Change these for different task
  FEATURE_SIZE = FLAGS.feature_size
  LABEL_SIZE = FLAGS.label_size
  TRAIN_TFRECORDS_FILE = FLAGS.train_tfrecords_path
  VALIDATE_TFRECORDS_FILE = FLAGS.validate_tfrecords_path
  TRAIN_TFRECORDS_FILE = "./data/inference_number/multiple_two/train.csv.tfrecords"
  VALIDATE_TFRECORDS_FILE = "./data/inference_number/multiple_two/validate.csv.tfrecords"


  epoch_number = FLAGS.epoch_number
  thread_number = FLAGS.thread_number
  batch_size = FLAGS.batch_size
  validate_batch_size = FLAGS.validate_batch_size
  min_after_dequeue = FLAGS.min_after_dequeue
  capacity = thread_number * batch_size + min_after_dequeue
  mode = FLAGS.mode
  checkpoint_path = FLAGS.checkpoint_path
  if not os.path.exists(checkpoint_path):
    os.makedirs(checkpoint_path)
  output_path = FLAGS.output_path
  if not os.path.exists(output_path):
    os.makedirs(output_path)

  def read_and_decode(filename_queue):
    reader = tf.TFRecordReader()
    _, serialized_example = reader.read(filename_queue)
    features = tf.parse_single_example(serialized_example,
                                       features={
                                           "label": tf.FixedLenFeature(
                                               [], tf.float32),
                                           "features": tf.FixedLenFeature(
                                               [FEATURE_SIZE], tf.float32),
                                       })
    label = features["label"]
    features = features["features"]
    return label, features

  # Read TFRecords files for training
  filename_queue = tf.train.string_input_producer(
      tf.train.match_filenames_once(TRAIN_TFRECORDS_FILE),
      num_epochs=epoch_number)
  label, features = read_and_decode(filename_queue)
  batch_labels, batch_features = tf.train.shuffle_batch(
      [label, features],
      batch_size=batch_size,
      num_threads=thread_number,
      capacity=capacity,
      min_after_dequeue=min_after_dequeue)

  # Read TFRecords file for validatioin
  validate_filename_queue = tf.train.string_input_producer(
      tf.train.match_filenames_once(VALIDATE_TFRECORDS_FILE),
      num_epochs=epoch_number)
  validate_label, validate_features = read_and_decode(validate_filename_queue)
  validate_batch_labels, validate_batch_features = tf.train.shuffle_batch(
      [validate_label, validate_features],
      batch_size=validate_batch_size,
      num_threads=thread_number,
      capacity=capacity,
      min_after_dequeue=min_after_dequeue)

  # Define the model
  input_units = FEATURE_SIZE
  hidden1_units = 8
  hidden2_units = 4
  hidden3_units = 2
  output_units = LABEL_SIZE

  output_units = 1


  def full_connect(inputs, weights_shape, biases_shape, is_train=True):
    with tf.device('/cpu:0'):
      weights = tf.get_variable("weights",
                                weights_shape,
                                initializer=tf.random_normal_initializer())
      biases = tf.get_variable("biases",
                               biases_shape,
                               initializer=tf.random_normal_initializer())
      layer = tf.matmul(inputs, weights) + biases

      if FLAGS.enable_bn and is_train:
        mean, var = tf.nn.moments(layer, axes=[0])
        scale = tf.get_variable("scale",
                                biases_shape,
                                initializer=tf.random_normal_initializer())
        shift = tf.get_variable("shift",
                                biases_shape,
                                initializer=tf.random_normal_initializer())
        layer = tf.nn.batch_normalization(layer, mean, var, shift, scale,
                                          FLAGS.bn_epsilon)
    return layer

  def full_connect_relu(inputs, weights_shape, biases_shape, is_train=True):
    layer = full_connect(inputs, weights_shape, biases_shape, is_train)
    layer = tf.nn.relu(layer)
    return layer

  def dnn_inference(inputs, is_train=True):
    with tf.variable_scope("layer1"):
      layer = full_connect_relu(inputs, [input_units, hidden1_units],
                                [hidden1_units], is_train)
    with tf.variable_scope("layer2"):
      layer = full_connect_relu(layer, [hidden1_units, hidden2_units],
                                [hidden2_units], is_train)
    with tf.variable_scope("layer3"):
      layer = full_connect_relu(layer, [hidden2_units, hidden3_units],
                                [hidden3_units], is_train)

    if FLAGS.enable_dropout and is_train:
      layer = tf.nn.dropout(layer, FLAGS.dropout_keep_prob)

    with tf.variable_scope("output"):
      layer = full_connect(layer, [hidden3_units, output_units],
                           [output_units], is_train)
    return layer

  def lr_inference(inputs, is_train=True):
    with tf.variable_scope("logistic_regression"):
      layer = full_connect(inputs, [input_units, output_units], [output_units])
    return layer

  def wide_and_deep_inference(inputs, is_train=True):
    return lr_inference(inputs, is_train) + dnn_inference(inputs, is_train)


  def lstm_inference(x, is_train=True):
    RNN_HIDDEN_UNITS = 9
    LABEL_SIZE = 1

    # x was [BATCH_SIZE, 32, 32, 3]
    # x changes to [32, BATCH_SIZE, 32, 3]
    #x = tf.transpose(x, [1, 0, 2, 3])
    x = tf.transpose(x, [1, 0])
    
    # x changes to [32 * BATCH_SIZE, 32 * 3]
    #x = tf.reshape(x, [-1, IMAGE_SIZE * RGB_CHANNEL_SIZE])
    # x changes to array of 32 * [BATCH_SIZE, 32 * 3]
    #x = tf.split(0, IMAGE_SIZE, x)
    x = tf.split(0, 9, x)


    weights = tf.Variable(tf.random_normal([RNN_HIDDEN_UNITS, LABEL_SIZE]))
    biases = tf.Variable(tf.random_normal([LABEL_SIZE]))

    # output size is 128, state size is (c=128, h=128)
    lstm_cell = rnn_cell.BasicLSTMCell(RNN_HIDDEN_UNITS, forget_bias=1.0)
    # outputs is array of 32 * [BATCH_SIZE, 128]
    outputs, states = rnn.rnn(lstm_cell, x, dtype=tf.float32)

    # outputs[-1] is [BATCH_SIZE, 128]
    return tf.matmul(outputs[-1], weights) + biases

  def inference(inputs, is_train=True):
    print("Use the model: {}".format(FLAGS.model))
    if FLAGS.model == "lr":
      return lr_inference(inputs, is_train)
    elif FLAGS.model == "dnn":
      return dnn_inference(inputs, is_train)
    elif FLAGS.model == "wide_and_deep":
      return wide_and_deep_inference(inputs, is_train)
    elif FLAGS.model == "lstm":
      return lstm_inference(inputs, is_train)
    else:
      print("Unknown model, exit now")
      exit(1)

  logits = inference(batch_features, True)
  '''
  batch_labels = tf.to_int64(batch_labels)
  
  cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(logits,
                                                                 batch_labels)
  loss = tf.reduce_mean(cross_entropy, name='loss')
  '''

  loss = tf.reduce_mean(tf.abs(logits - batch_labels))


  with tf.device("/cpu:0"):
    global_step = tf.Variable(0, name='global_step', trainable=False)

  if FLAGS.enable_lr_decay:
    print("Enable learning rate decay rate: {}".format(FLAGS.lr_decay_rate))
    starter_learning_rate = FLAGS.learning_rate
    learning_rate = tf.train.exponential_decay(starter_learning_rate,
                                               global_step,
                                               100000,
                                               FLAGS.lr_decay_rate,
                                               staircase=True)
  else:
    learning_rate = FLAGS.learning_rate

  print("Use the optimizer: {}".format(FLAGS.optimizer))
  if FLAGS.optimizer == "sgd":
    optimizer = tf.train.GradientDescentOptimizer(learning_rate)
  elif FLAGS.optimizer == "adadelta":
    optimizer = tf.train.AdadeltaOptimizer(learning_rate)
  elif FLAGS.optimizer == "adagrad":
    optimizer = tf.train.AdagradOptimizer(learning_rate)
  elif FLAGS.optimizer == "adam":
    optimizer = tf.train.AdamOptimizer(learning_rate)
  elif FLAGS.optimizer == "ftrl":
    optimizer = tf.train.FtrlOptimizer(learning_rate)
  elif FLAGS.optimizer == "rmsprop":
    optimizer = tf.train.RMSPropOptimizer(learning_rate)
  else:
    print("Unknow optimizer: {}, exit now".format(FLAGS.optimizer))
    exit(1)

  train_op = optimizer.minimize(loss, global_step=global_step)

  tf.get_variable_scope().reuse_variables()

  '''
  # Define accuracy op for train data
  train_accuracy_logits = inference(batch_features, False)
  train_softmax = tf.nn.softmax(train_accuracy_logits)
  train_correct_prediction = tf.equal(
      tf.argmax(train_softmax, 1), batch_labels)
  train_accuracy = tf.reduce_mean(tf.cast(train_correct_prediction,
                                          tf.float32))

  # Define auc op for validate data
  batch_labels = tf.cast(batch_labels, tf.int32)
  sparse_labels = tf.reshape(batch_labels, [-1, 1])
  derived_size = tf.shape(batch_labels)[0]
  indices = tf.reshape(tf.range(0, derived_size, 1), [-1, 1])
  concated = tf.concat(1, [indices, sparse_labels])
  outshape = tf.pack([derived_size, LABEL_SIZE])
  new_batch_labels = tf.sparse_to_dense(concated, outshape, 1.0, 0.0)
  _, train_auc = tf.contrib.metrics.streaming_auc(train_softmax,
                                                  new_batch_labels)

  # Define accuracy op for validate data
  validate_accuracy_logits = inference(validate_batch_features, False)
  validate_softmax = tf.nn.softmax(validate_accuracy_logits)
  validate_batch_labels = tf.to_int64(validate_batch_labels)
  validate_correct_prediction = tf.equal(
      tf.argmax(validate_softmax, 1), validate_batch_labels)
  validate_accuracy = tf.reduce_mean(tf.cast(validate_correct_prediction,
                                             tf.float32))

  # Define auc op for validate data
  validate_batch_labels = tf.cast(validate_batch_labels, tf.int32)
  sparse_labels = tf.reshape(validate_batch_labels, [-1, 1])
  derived_size = tf.shape(validate_batch_labels)[0]
  indices = tf.reshape(tf.range(0, derived_size, 1), [-1, 1])
  concated = tf.concat(1, [indices, sparse_labels])
  outshape = tf.pack([derived_size, LABEL_SIZE])
  new_validate_batch_labels = tf.sparse_to_dense(concated, outshape, 1.0, 0.0)
  _, validate_auc = tf.contrib.metrics.streaming_auc(validate_softmax,
                                                     new_validate_batch_labels)

  # Define inference op
  inference_features = tf.placeholder("float", [None, FEATURE_SIZE])
  inference_logits = inference(inference_features, False)
  inference_softmax = tf.nn.softmax(inference_logits)
  inference_op = tf.argmax(inference_softmax, 1)
  '''

  # Initialize saver and summary
  checkpoint_file = checkpoint_path + "/checkpoint.ckpt"
  latest_checkpoint = tf.train.latest_checkpoint(checkpoint_path)
  steps_to_validate = FLAGS.steps_to_validate
  init_op = tf.initialize_all_variables()
  tf.scalar_summary("loss", loss)
  '''
  tf.scalar_summary("train_accuracy", train_accuracy)
  tf.scalar_summary("train_auc", train_auc)
  tf.scalar_summary("validate_accuracy", validate_accuracy)
  tf.scalar_summary("validate_auc", validate_auc)
  '''
  saver = tf.train.Saver()
  keys_placeholder = tf.placeholder(tf.int32, shape=[None, 1])
  keys = tf.identity(keys_placeholder)
  '''
  tf.add_to_collection("inputs",
                       json.dumps({'key': keys_placeholder.name,
                                   'features': inference_features.name}))
  tf.add_to_collection("outputs",
                       json.dumps({'key': keys.name,
                                   'softmax': inference_softmax.name,
                                   'prediction': inference_op.name}))
  '''

  # Create session to run
  with tf.Session() as sess:
    summary_op = tf.merge_all_summaries()
    writer = tf.train.SummaryWriter(output_path, sess.graph)
    sess.run(init_op)
    sess.run(tf.initialize_local_variables())

    if mode == "train":
      if latest_checkpoint:
        print("Load the checkpoint from {}".format(latest_checkpoint))
        saver.restore(sess, latest_checkpoint)

      # Get coordinator and run queues to read data
      coord = tf.train.Coordinator()
      threads = tf.train.start_queue_runners(coord=coord, sess=sess)

      start_time = datetime.datetime.now()
      try:
        while not coord.should_stop():
          _, loss_value, step = sess.run([train_op, loss, global_step])

          #print(sess.run(batch_labels))
          #print(sess.run(logits))

          if step % steps_to_validate == 0:
            '''
            train_accuracy_value, train_auc_value, validate_accuracy_value, validate_auc_value, summary_value = sess.run(
                [train_accuracy, train_auc, validate_accuracy, validate_auc,
                 summary_op])
            '''

            end_time = datetime.datetime.now()
            '''
            print(
                "[{}] Step: {}, loss: {}, train_acc: {}, train_auc: {}, valid_acc: {}, valid_auc: {}".format(
                    end_time - start_time, step, loss_value,
                    train_accuracy_value, train_auc_value,
                    validate_accuracy_value, validate_auc_value))
            '''
            print("[{}] Step: {}, loss: {}".format(end_time - start_time, step, loss_value))
            '''
            writer.add_summary(summary_value, step)
            '''
            saver.save(sess, checkpoint_file, global_step=step)
            start_time = end_time
      except tf.errors.OutOfRangeError:
        print("Exporting trained model to {}".format(FLAGS.model_path))
        '''
        model_exporter = exporter.Exporter(saver)
        model_exporter.init(sess.graph.as_graph_def(),
                            named_graph_signatures={
                                'inputs': exporter.generic_signature(
                                    {"keys": keys_placeholder,
                                     "features": inference_features}),
                                'outputs': exporter.generic_signature(
                                    {"keys": keys,
                                     "softmax": inference_softmax,
                                     "prediction": inference_op})
                            })
        model_exporter.export(FLAGS.model_path,
                              tf.constant(FLAGS.export_version), sess)
        print 'Done exporting!'
        '''

      finally:
        coord.request_stop()

      # Wait for threads to exit
      coord.join(threads)

    elif mode == "export":
      print("Start to export model directly")
      '''
      # Load the checkpoint files
      if latest_checkpoint:
        print("Load the checkpoint from {}".format(latest_checkpoint))
        saver.restore(sess, latest_checkpoint)
      else:
        print("No checkpoint found, exit now")
        exit(1)

      # Export the model files
      print("Exporting trained model to {}".format(FLAGS.model_path))
      model_exporter = exporter.Exporter(saver)
      model_exporter.init(sess.graph.as_graph_def(),
                          named_graph_signatures={
                              'inputs': exporter.generic_signature(
                                  {"keys": keys_placeholder,
                                   "features": inference_features}),
                              'outputs': exporter.generic_signature(
                                  {"keys": keys,
                                   "softmax": inference_softmax,
                                   "prediction": inference_op})
                          })
      model_exporter.export(FLAGS.model_path,
                            tf.constant(FLAGS.export_version), sess)
      '''
    '''
    elif mode == "inference":
      print("Start to run inference")
      start_time = datetime.datetime.now()

      inference_result_file_name = "./inference_result.txt"
      inference_test_file_name = "./data/cancer_test.csv"

      inference_data = np.genfromtxt(inference_test_file_name, delimiter=',')
      inference_data_features = inference_data[:, 0:9]
      inference_data_labels = inference_data[:, 9]

      # Restore wights from model file
      if latest_checkpoint:
        print("Load the checkpoint from {}".format(latest_checkpoint))
        saver.restore(sess, latest_checkpoint)
      else:
        print("No model found, exit now")
        exit(1)

      prediction, prediction_softmax = sess.run(
          [inference_op, inference_softmax],
          feed_dict={inference_features: inference_data_features})

      end_time = datetime.datetime.now()
      print("[{}] Inference result: {}".format(end_time - start_time,
                                               prediction))

      # Compute accuracy
      label_number = len(inference_data_labels)
      correct_label_number = 0
      for i in range(label_number):
        if inference_data_labels[i] == prediction[i]:
          correct_label_number += 1
      accuracy = float(correct_label_number) / label_number

      # Compute auc
      expected_labels = np.array(inference_data_labels)
      predict_labels = prediction_softmax[:, 0]
      fpr, tpr, thresholds = metrics.roc_curve(expected_labels,
                                               predict_labels,
                                               pos_label=0)
      auc = metrics.auc(fpr, tpr)
      print("For inference data, accuracy: {}, auc: {}".format(accuracy, auc))

      np.savetxt(inference_result_file_name, prediction, delimiter=",")
      print("Save result to file: {}".format(inference_result_file_name))
    '''

if __name__ == "__main__":
  main()
