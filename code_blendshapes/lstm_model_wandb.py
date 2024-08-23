import wandb
import numpy as np
import pandas as pd
import random
from sklearn.model_selection import KFold
from keras.models import Sequential
from keras.layers import LSTM, Dense, Dropout, BatchNormalization, Input, Bidirectional
from keras.callbacks import ModelCheckpoint
from keras.regularizers import l1_l2, l1, l2
from keras.utils import to_categorical
import tensorflow as tf
from create_data_splits import create_data_splits
from get_metrics import get_metrics

def train(df):

    wandb.init()
    config = wandb.config
    print(config)

    seed_value = 42
    np.random.seed(seed_value)
    random.seed(seed_value)
    tf.random.set_seed(seed_value)

    num_lstm_layers = config.num_lstm_layers
    lstm_units = config.lstm_units
    batch_size = config.batch_size
    epochs = config.epochs
    activation = config.activation_function
    use_bidirectional = config.use_bidirectional
    dropout = config.dropout_rate
    optimizer = config.optimizer
    learning_rate = config.learning_rate
    dense_units = config.dense_units
    kernel_regularizer = config.recurrent_regularizer
    loss = config.loss
    sequence_length = config.sequence_length

    splits = create_data_splits(
        df,
        fold_no=0,
        num_folds=5,
        seed_value=42,
        sequence_length=sequence_length
    )

    if splits is None:
        return

    X_train, X_val, X_test, y_train, y_val, y_test, X_train_sequences, y_train_sequences, X_val_sequences, y_val_sequences, X_test_sequences, y_test_sequences, sequence_length = splits

    if loss == "categorical_crossentropy":
        y_train_sequences = to_categorical(y_train_sequences)
        y_val_sequences = to_categorical(y_val_sequences)
        y_test_sequences = to_categorical(y_test_sequences)
        num_classes = y_train_sequences.shape[1]
    else:
        num_classes = 1

    print("X_train_sequences shape:", X_train_sequences.shape)
    print("X_val_sequences shape:", X_val_sequences.shape)
    print("X_test_sequences shape:", X_test_sequences.shape)

    model = Sequential()
    model.add(Input(shape=(sequence_length, X_train_sequences.shape[2])))

    if kernel_regularizer == "l1":
        reg = l1(0.01)
    elif kernel_regularizer == "l2":
        reg = l2(0.01)
    elif kernel_regularizer == "l1_l2":
        reg = l1_l2(0.01, 0.01)
    else:
        reg = None

    for _ in range(num_lstm_layers - 1):
        if use_bidirectional:
            model.add(Bidirectional(LSTM(lstm_units, return_sequences=True, activation=activation, kernel_regularizer=reg)))
        else:
            model.add(LSTM(lstm_units, return_sequences=True, activation=activation, kernel_regularizer=reg))
        model.add(Dropout(dropout))
        model.add(BatchNormalization())

    if use_bidirectional:
        model.add(Bidirectional(LSTM(lstm_units, activation=activation)))
    else:
        model.add(LSTM(lstm_units, activation=activation))
    
    model.add(Dropout(dropout))
    model.add(BatchNormalization())

    model.add(Dense(dense_units, activation=activation))
    
    if loss == "categorical_crossentropy":
        model.add(Dense(num_classes, activation="softmax"))
    else:
        model.add(Dense(1, activation="sigmoid"))

    if optimizer == 'adam':
        optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)
    elif optimizer == 'sgd':
        optimizer = tf.keras.optimizers.SGD(learning_rate=learning_rate)
    elif optimizer == 'adadelta':
        optimizer = tf.keras.optimizers.Adadelta(learning_rate=learning_rate)
    elif optimizer == 'rmsprop':
        optimizer = tf.keras.optimizers.RMSprop(learning_rate=learning_rate)

    model.summary()
    
    model.compile(optimizer=optimizer, loss=loss, metrics=['accuracy', 'Precision', 'Recall', 'AUC'])

    model_checkpoint = ModelCheckpoint("training/best_model.keras", monitor="val_accuracy", save_best_only=True)
    
    model_history = model.fit(
        X_train_sequences, y_train_sequences,
        epochs=epochs,
        batch_size=batch_size,
        validation_data=(X_val_sequences, y_val_sequences),
        callbacks=[model_checkpoint],
        verbose=2
    )

    for epoch in range(len(model_history.history['loss'])):
        metrics = {
            'epoch': epoch,
            'loss': model_history.history['loss'][epoch],
            'val_loss': model_history.history['val_loss'][epoch]
        }
        if 'accuracy' in model_history.history:
            metrics['accuracy'] = model_history.history['accuracy'][epoch]
        if 'val_accuracy' in model_history.history:
            metrics['val_accuracy'] = model_history.history['val_accuracy'][epoch]
        if 'precision' in model_history.history:
            metrics['precision'] = model_history.history['precision'][epoch]
        if 'val_precision' in model_history.history:
            metrics['val_precision'] = model_history.history['val_precision'][epoch]
        if 'recall' in model_history.history:
            metrics['recall'] = model_history.history['recall'][epoch]
        if 'val_recall' in model_history.history:
            metrics['val_recall'] = model_history.history['val_recall'][epoch]
        if 'auc' in model_history.history:
            metrics['auc'] = model_history.history['auc'][epoch]
        if 'val_auc' in model_history.history:
            metrics['val_auc'] = model_history.history['val_auc'][epoch]
        
        wandb.log(metrics)

    y_predict_probs = model.predict(X_test_sequences)

    if loss == "categorical_crossentropy":
        y_pred = np.argmax(y_predict_probs, axis=1)
        y_test_sequences = np.argmax(y_test_sequences, axis=1)
    else:
        y_pred = (y_predict_probs > 0.5).astype(int).flatten()
    
    y_test_sequences = y_test_sequences.astype(int).flatten()

    test_metrics = get_metrics(y_pred, y_test_sequences, tolerance=1)
    #put "test" before metrics
    test_metrics = {f"test_{k}": v for k, v in test_metrics.items()}
    
    wandb.log(test_metrics)
    print(test_metrics)


def main():
    global df
    df = pd.read_csv("../../data/training_data.csv")

    sweep_config = {
        'method': 'random',
        'name': 'lstm_neckface',
        'parameters': {
            'use_bidirectional': {'values': [True, False]},
            'num_lstm_layers': {'values': [1, 2, 3]},
            'lstm_units': {'values': [64, 128, 256]},
            'dropout_rate': {'values': [0.0, 0.3, 0.5, 0.8]},
            'dense_units': {'values': [32, 64, 128]},
            'activation_function': {'values': ['tanh', 'relu', 'sigmoid']},
            'optimizer': {'values': ['adam', 'sgd', 'adadelta', 'rmsprop']},
            'learning_rate': {'values': [0.001, 0.01, 0.005]},
            'batch_size': {'values': [32, 64, 128]},
            'epochs': {'value': 500},
            'recurrent_regularizer': {'values': ['l1', 'l2', 'l1_l2']},
            'loss' : {'values' : ["binary_crossentropy", "categorical_crossentropy"]},
            'sequence_length' : {'values' : [1, 5, 15, 30]}
        }
    }

    def train_wrapper():
        train(df)

    sweep_id = wandb.sweep(sweep=sweep_config, project="lstm_neckface")
    wandb.agent(sweep_id, function=train_wrapper)

if __name__ == '__main__':
    main()
