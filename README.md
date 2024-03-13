# C10-Audio-Based-Interaction-Recognition

## Challenge

To participate and submit to this challenge, register at the [EPIC-Sounds Audio-Based Interaction Detection Codalab Challenge](https://codalab.lisn.upsaclay.fr/competitions/707). The labelled train/val annoations are available on the [EPIC-Sounds annotations repo](https://github.com/epic-kitchens/epic-sounds-annotations).

This repo is a modified version of the existing [Action Detection Challenge](https://github.com/epic-kitchens/C2-Action-Detection).

**NOTE:** For this version of the challenge (version "0.1"), the class "background" (class_id=13) has been redacted from the test set. The evaluation code `audio_based_interaction_detection.py` will remove background labels from the evaluation.

## Evaluation Code

This repository contains the official code to evaluate audio-based interaction detection methods on the EPIC-SOUNDS validation set. Parts of the evaluation code have been adapted from [ActivityNet](https://github.com/activitynet/ActivityNet/blob/master/Evaluation/eval_detection.py).

To use this code, move to the `EvaluationCode` directory:

```[bash]
cd EvaluationCode
```

### Requirements

In order to use the evaluation code, you will need to install a few packages. You can install these requirements with:

```[bash]
pip install -r requirements.txt
```

### Usage

You can use this evaluation code to evaluate submissions on the validation set in the official JSON format. To do so, you will need to first download the public EPIC-SOUNDS annotations with:

```[bash]
export PATH_TO_ANNOTATIONS=/desired/path/to/annotations
git clone https://github.com/epic-kitchens/epic-sounds-annotations.git $PATH_TO_ANNOTATIONS
```

You can then evaluate your json file with:

```[bash]
python evaluate_detection_json_ek100.py /path/to/json $PATH_TO_ANNOTATIONS/EPIC_Sounds_validation.pkl
```

Where `/path/to/json` is the path to the json file to be evaluated and `/path/to/annotations` is the path to the cloned `epic-sounds-annotations` repository.

### Example json

As an example, we provide a json file generated with the baseline on the validation set. You can evaluate the json file with:

```[bash]
python audio_based_interaction_detection.py actionformer_baseline_validation.json $PATH_TO_ANNOTATIONS/EPIC_Sounds_validation.pkl
```

## Audio-Based Interaction Detection Baseline

The baseline used for this challenge is [ActionFormer](https://arxiv.org/abs/2202.07925).

In the following, we provide instructions to train/evaluate this baseline.

### Baseline Requirements

We recommend to use [Anaconda](http://anaconda.org/). You follow the installation steps in the [ActionFormer GitHub](https://github.com/happyharrycn/actionformer_release) to install the necessary packages to run the baseline.

### Features

We provide auditory slowfast features used train the baseline. You can download the features with: (PENDING)

Save the features under the path `baseline/data/epic_sounds/auditory_slowfast_features` in this repository.

### Model

You can download the model used to report baseline results in the paper [here](https://www.dropbox.com/scl/fi/uszgvn6xz7l543ald1n0p/EPIC_Sounds_ActionFormer.tar?rlkey=mk08iyfzr1wn5dxs3hwxy82m1&dl=0).

### Training

 You can train the model by moving to the `baseline` folder and running:

```[bash]
 python train.py configs/epic_sounds_auditory_slowfast.yaml --output reproduce
```

### Validation

You can evaluate the model by moving to the `baseline` folder and running:

```[bash]
python eval.py configs/epic_sounds_auditory_slowfast.yaml <path_to_checkpoint>
```

### Compute Test Detections

You can compute the test detections using the following command:

```[bash]
python eval.py --saveonly configs/epic_sounds_auditory_slowfast_test.yaml <path_to_checkpoint>
```

After running the command a .pkl containing the test detections will be generated. you can convert them to a JSON file using `python create_json.py <PATH_TO_PKL>` in the `EvaluationCode` folder. This .json file can then be evaluated using:

```[bash]
python audio_based_interaction_detection.py  test.json <PATH_TO_ANNOTIONS>
```
