import argparse
import pickle
import json

from textwrap import dedent


parser = argparse.ArgumentParser(
    description="Create JSON submission from actionformer .pkl file",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    "path_to_pkl",
    help = "Path to the pkl file"
)
parser.add_argument(
    "--sls-pt",
    choices=[0, 1, 2, 3, 4, 5],
    default=2,
    type=int,
    help=dedent(
        """\
        Level of pre-training supervision used by your model:

        0: No pretraining
        1: Pretrained on public image dataset
        2: Pretrained on public image and video datasets
        3: Pretrained using self-supervision on public data
        4: Pretrained using self-supervision on public data and on EPIC-Kitchens
        5: Pretrained on private data

        See https://github.com/epic-kitchens/sls for the canonical reference on SLS-PT.

        (default: 2)
        """
    ),
)
parser.add_argument(
    "--sls-tl",
    choices=[0, 1, 2, 3, 4, 5],
    default=3,
    type=int,
    help=dedent(
        """\
        Level of training labels used by your model:

        0: No supervision
        1: Weak-supervision [video-level] (Can use narration / verb_class /
           noun_class, but no temporal or spatial annotations)
        2: Weak-supervision [temporal] (Can use narration_timestamp in addition to
           supervision in 1)
        3: Full-supervision [temporal] (Can use start_frame / stop_frame in addition
           to supervision in 1/2)
        4: Full-supervision [spatio-temporal] (Can use spatial-annotations produced
           by pretrained detection/segmentation model in addition to supervision
           defined in 1/2/3)
        5: Full-supervision [spatio-temporal+] (Can use prior knowledge outside of
           labels specified in addition to supervision defined in 1/2/3/4)

        All additional labels used in training the model should be made available.

        See https://github.com/epic-kitchens/sls for the canonical reference on SLS-TL .

        (default: 3)"""
    ),
)
parser.add_argument(
    "--sls-td",
    choices=[0, 1, 2, 3, 4, 5],
    default=4,
    type=int,
    help=dedent(
        """\
        Level of training supervision used by your model:

        0: Zero-shot learning (no training data used, only class knowledge incorporated)
        1: Few-shot learning (trained with up to 5 examples of each verb-class or
           noun-class in the dataset)
        2: Efficient learning (A random sample of no more than 25%% of the training
           data  was used to train the model and the sample was not optimised)
        3: Training set (The full training split was used to train the model)
        4: Train+val (The training and validation sets were used to train the model,
           typically after optimising hyperparameters using the validation set.)
        5: Train+val+ (All labelled data in train+val was used in addition to other
           labelled or unlabelled data from additional source [different from
           pretraining])

        All additional data used in training the model should be made available.

        See https://github.com/epic-kitchens/sls for the canonical reference on SLS-TD

        (default: 4)"""
    ),
)
parser.add_argument(
    "--t_mod",
    choices=[0, 1, 2],
    default=0,
    type=int,
    help=dedent(
        """\
        The modality used to train the model:

        0: Audio-Only
        1: Video-Only
        2: Audio-Visual

        (default: 0)"""
    ),
)



def main(args):
    print("Loading Files")
    with open(args.path_to_pkl, 'rb') as f:
        results = pickle.load(f)


    submission_results = {}

    for p in range(len(results['video-id'])):
        video_id = results['video-id'][p]
        interaction = results['label'][p]
        score = results['score'][p]

        start = results['t-start'][p]
        stop = results['t-end'][p]

        entry = {
                "interaction": interaction,
                "score": float(score),
                "segment": [float(start), float(stop)]
            }
        if video_id in submission_results:
            submission_results[video_id].append(entry)
        else:
            submission_results[video_id] = [entry]

    print("Total Entries:", sum([len(v) for k, v in submission_results.items()]))

    submission = {
            "version": "0.1",
            "challenge": "audio_based_interaction_detection",
            "sls_pt": args.sls_pt,
            "sls_tl": args.sls_tl,
            "sls_td": args.sls_td,
            "t_mod": args.t_mod,
            "results": submission_results
        }

    with open(f"test.json", 'w') as f:
        json.dump(submission, f, indent=4, separators=(',', ': '))

if __name__ == "__main__":
    main(parser.parse_args())