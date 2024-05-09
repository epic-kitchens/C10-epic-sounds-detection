#!/usr/bin/env python3
import argparse
import logging
import sys
from pathlib import Path
import json
import pandas as pd
import numpy as np
from joblib import Parallel, delayed
from typing import List
from typing import Tuple
from typing import Dict
from typing import Iterable
from typing import Union

_MINUTES_TO_SECONDS = 60
_HOURS_TO_SECONDS = 60 * 60

def write_metrics(metrics, f):
    for name, value in metrics.items():
        f.write("{name}: {value}\n".format(name=name, value=value))


def timestamp_to_seconds(timestamp):
    hours, minutes, seconds = map(float, timestamp.split(":"))
    total_seconds = hours * _HOURS_TO_SECONDS + minutes * _MINUTES_TO_SECONDS + seconds
    return total_seconds

def load_gt_segmentations(annotations):
    gt_base = pd.DataFrame({
        'video-id' : annotations['video_id'],
        't-start' : annotations['start_timestamp'].apply(timestamp_to_seconds),
        't-end': annotations['stop_timestamp'].apply(timestamp_to_seconds),
        'interactions': annotations['class_id'],
        'narration' : annotations.index
    })

    gt_base['label'] = annotations['class_id']


    return gt_base

def load_predicted_segmentations(submission):
    results = submission['results']
    vids = []
    starts = []
    stops = []
    interactions = []
    scores = []

    for k, v in results.items():
        starts += [float(vv['segment'][0]) for vv in v]
        stops += [float(vv['segment'][1]) for vv in v]
        interactions += [int(vv['interaction']) for vv in v]
        vids += [k] * len(v)
        scores += [float(vv['score']) for vv in v]

    pred_base = pd.DataFrame({
        'video-id': vids,
        't-start': starts,
        't-end': stops,
        'score': scores,
        'interaction' : interactions
    })

    pred_base['label'] = interactions

    return pred_base

class ANETdetection(object):
    """Adapted from https://github.com/activitynet/ActivityNet/blob/master/Evaluation/eval_detection.py"""

    def __init__(self, annotations, submission,
                tiou_thresholds=np.linspace(0.1, 0.5, 5)):

        self.tiou_thresholds = tiou_thresholds
        self.ap = None

        # Import ground truth and predictions.
        self.ground_truth = load_gt_segmentations(annotations)
        self.prediction = load_predicted_segmentations(submission)

        # Remove predictions of non-existing labels, this prevents double mapping of labels not in the ground truth
        self.prediction = self.prediction[self.prediction['label'].isin(self.ground_truth['label'].unique())]

        self.activity_index = {j: i for i, j in enumerate(sorted(self.ground_truth['label'].unique()))}

        self.ground_truth['label']=self.ground_truth['label'].replace(self.activity_index)
        self.prediction['label']=self.prediction['label'].replace(self.activity_index)


    def _get_predictions_with_label(self, prediction_by_label, label_name, cidx):
        """Get all predicitons of the given label. Return empty DataFrame if there
        is no predcitions with the given label.
        """
        try:
            res = prediction_by_label.get_group(cidx).reset_index(drop=True)
            #print('%d predictions of label \'%s\' were provdied.' % (len(res),label_name))
            return res
        except:
            #print('Warning: No predictions of label \'%s\' were provdied.' % label_name)
            return pd.DataFrame()

    def wrapper_compute_average_precision(self):
        """Computes average precision for each class in the subset.
        """
        ap = np.zeros((len(self.tiou_thresholds), len(self.activity_index)))

        # Adaptation to query faster
        ground_truth_by_label = self.ground_truth.groupby('label')
        prediction_by_label = self.prediction.groupby('label')

        results = Parallel(n_jobs=16)(
            delayed(compute_average_precision_detection)(
                ground_truth=ground_truth_by_label.get_group(cidx).reset_index(drop=True),
                prediction=self._get_predictions_with_label(prediction_by_label, label_name, cidx),
                tiou_thresholds=self.tiou_thresholds,
            ) for label_name, cidx in self.activity_index.items())

        self.correct_predictions = []
        for i, cidx in enumerate(self.activity_index.values()):
            ap[:,cidx], predictions = results[i]
            self.correct_predictions.append(predictions)
        self.correct_predictions = pd.concat(self.correct_predictions)

        return ap

    def evaluate(self):
        """Evaluates a prediction file. For the detection task we measure the
        interpolated mean average precision to measure the performance of a
        method.
        """
        self.ap = self.wrapper_compute_average_precision()

        self.mAP = self.ap.mean(axis=1)
        self.average_mAP = self.mAP.mean()

        return self.mAP, self.average_mAP

def compute_average_precision_detection(ground_truth, prediction, tiou_thresholds=np.linspace(0.1, 0.5, 5)):
    """Compute average precision (detection task) between ground truth and
    predictions data frames. If multiple predictions occurs for the same
    predicted segment, only the one with highest score is matches as
    true positive. This code is greatly inspired by Pascal VOC devkit.
    Parameters
    ----------
    ground_truth : df
        Data frame containing the ground truth instances.
        Required fields: ['video-id', 't-start', 't-end']
    prediction : df
        Data frame containing the prediction instances.
        Required fields: ['video-id, 't-start', 't-end', 'score']
    tiou_thresholds : 1darray, optional
        Temporal intersection over union threshold.
    Outputs
    -------
    ap : float
        Average precision score.
    """

    ap = np.zeros(len(tiou_thresholds))
    if prediction.empty:
        return ap, pd.DataFrame()

    npos = float(len(ground_truth))
    lock_gt = np.ones((len(tiou_thresholds),len(ground_truth))) * -1
    # Sort predictions by decreasing score order.
    sort_idx = prediction['score'].values.argsort()[::-1]
    prediction = prediction.loc[sort_idx].reset_index(drop=True)

    # Initialize true positive and false positive vectors.
    tp = np.zeros((len(tiou_thresholds), len(prediction)))
    fp = np.zeros((len(tiou_thresholds), len(prediction)))

    # Adaptation to query faster
    ground_truth_gbvn = ground_truth.groupby('video-id')

    correct_preds = []
    # Assigning true positive to truly grount truth instances.
    for idx, this_pred in prediction.iterrows():
        correct_preds.append(pd.Series({
            'video-id': this_pred['video-id'],
            'start': this_pred['t-start'],
            'end': this_pred['t-end'],
            'score': this_pred['score'],
            'interaction': this_pred['interaction'],
            'correct@0.5': 0,
            'matched_gt': None
        }))
        try:
            # Check if there is at least one ground truth in the video associated.
            ground_truth_videoid = ground_truth_gbvn.get_group(this_pred['video-id'])
        except Exception as e:
            fp[:, idx] = 1
            continue

        this_gt = ground_truth_videoid.reset_index()
        tiou_arr = segment_iou(this_pred[['t-start', 't-end']].values,
                               this_gt[['t-start', 't-end']].values)
        # We would like to retrieve the predictions with highest tiou score.
        tiou_sorted_idx = tiou_arr.argsort()[::-1]
        for tidx, tiou_thr in enumerate(tiou_thresholds):
            for jdx in tiou_sorted_idx:
                if tiou_arr[jdx] < tiou_thr:
                    fp[tidx, idx] = 1
                    break
                if lock_gt[tidx, this_gt.loc[jdx]['index']] >= 0:
                    continue
                # Assign as true positive after the filters above.
                tp[tidx, idx] = 1
                lock_gt[tidx, this_gt.loc[jdx]['index']] = idx
                if tidx==tp.shape[0]//2-1:
                    correct_preds[-1]['correct@0.5']=1
                    correct_preds[-1]['matched_gt'] = this_gt.loc[jdx]['narration']
                break

            if fp[tidx, idx] == 0 and tp[tidx, idx] == 0:
                fp[tidx, idx] = 1


    tp_cumsum = np.cumsum(tp, axis=1).astype(np.float)
    fp_cumsum = np.cumsum(fp, axis=1).astype(np.float)
    recall_cumsum = tp_cumsum / npos

    precision_cumsum = tp_cumsum / (tp_cumsum + fp_cumsum)

    for tidx in range(len(tiou_thresholds)):
        ap[tidx] = interpolated_prec_rec(precision_cumsum[tidx,:], recall_cumsum[tidx,:])

    return ap, pd.DataFrame(correct_preds)

def segment_iou(target_segment, candidate_segments):
    """Compute the temporal intersection over union between a
    target segment and all the test segments.
    Parameters
    ----------
    target_segment : 1d array
        Temporal target segment containing [starting, ending] times.
    candidate_segments : 2d array
        Temporal candidate segments containing N x [starting, ending] times.
    Outputs
    -------
    tiou : 1d array
        Temporal intersection over union score of the N's candidate segments.
    """
    tt1 = np.maximum(target_segment[0], candidate_segments[:, 0])
    tt2 = np.minimum(target_segment[1], candidate_segments[:, 1])
    # Intersection including Non-negative overlap score.
    segments_intersection = (tt2 - tt1).clip(0)
    # Segment union.
    segments_union = (candidate_segments[:, 1] - candidate_segments[:, 0]) \
                     + (target_segment[1] - target_segment[0]) - segments_intersection
    # Compute overlap as the ratio of the intersection
    # over union of two segments.
    tIoU = segments_intersection.astype(float) / segments_union
    return tIoU

def interpolated_prec_rec(prec, rec):
    """Interpolated AP - VOCdevkit from VOC 2011.
    """
    mprec = np.hstack([[0], prec, [0]])
    mrec = np.hstack([[0], rec, [1]])
    for i in range(len(mprec) - 1)[::-1]:
        mprec[i] = max(mprec[i], mprec[i + 1])
    idx = np.where(mrec[1::] != mrec[0:-1])[0] + 1
    ap = np.sum((mrec[idx] - mrec[idx - 1]) * mprec[idx])
    return ap

__here__ = Path(__file__).absolute().parent
sys.path.append(str(__here__.parent))

LOG = logging.getLogger("evaluate_action_detection")

parser = argparse.ArgumentParser(
    description="Evaluate EPIC-Sounds audio-based interaction detection challenge results",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    "path_to_json",
    help = "Path to the json file to be evaluated"
)
parser.add_argument(
    "path_to_annotations",
    type=Path,
    help = "Path to the annotations pkl"
)
parser.add_argument("--interaction-count", default=44, type=int)


class ValidationException(Exception):
    pass


class MissingPropertyException(ValidationException):
    def __init__(self, property: str, uid: int = None) -> None:
        self.property = property
        self.uid = uid

    def __str__(self):
        message = "Missing '{}' property".format(self.property)
        if self.uid is not None:
            message += " for uids {}.".format(self.uid)
        return message


class UnsupportedSubmissionVersionException(ValidationException):
    def __init__(self, valid_versions: Iterable[str], ver: str) -> None:
        self.valid_versions = valid_versions
        self.version = ver

    def __str__(self):
        return "Submission version '{}' is not supported, valid versions: {}".format(
            self.version, ", ".join(self.valid_versions)
        )


class UnsupportedChallengeException(ValidationException):
    def __init__(self, valid_challenges: Iterable[str], challenge: str) -> None:
        self.valid_challenges = valid_challenges
        self.challenge = challenge

    def __str__(self):
        return "Challenge '{}' is not supported, valid challenges: {}".format(
            self.challenge, ", ".join(self.valid_challenges)
        )

class InvalidClassEntry(ValidationException):
    def __init__(self, task: str, invalid_entry: str) -> None:
        self.task = task
        self.invalid_entry = invalid_entry

    def __str__(self):
        return "Found invalid {} class '{}'".format(
            self.task, str(self.invalid_entry)
        )


class MissingScoreException(ValidationException):
    def __init__(self, entry_type: str, uid: int, missing_classes: np.ndarray) -> None:
        self.entry_type = entry_type
        self.uid = uid
        self.missing_classes = missing_classes

    def __str__(self):
        return "The following {} scores are not included for uid {}: {}.".format(
            self.entry_type, self.uid, ", ".join(self.missing_classes.astype(str))
        )


class UnexpectedScoreEntriesException(ValidationException):
    def __init__(self, task: str, uid: int, unexpected_classes: np.ndarray) -> None:
        self.task = task
        self.uid = uid
        self.unexpected_classes = unexpected_classes

    def __str__(self):
        return "Found the following unexpected {} entries for uid {}: {}.".format(
            self.task, self.uid, ", ".join(self.unexpected_classes.astype(str))
        )


class InvalidNumberOfActionScoresException(ValidationException):
    def __init__(self, uid: str, expected_count: int, actual_count: int) -> None:
        self.uid = uid
        self.expected_count = expected_count
        self.actual_count = actual_count

    def __str__(self):
        return (
            "The number of action scores provided for segment {} should be equal to {} "
            "but found {} scores."
        ).format(self.uid, self.expected_count, self.actual_count)

class InvalidNumberOfTimestampsException(ValidationException):
    def __init__(self, expected_count: int, actual_count: int) -> None:
        self.expected_count = expected_count
        self.actual_count = actual_count

    def __str__(self):
        return (
            "The number of action timestamps provided for a segment should be equal to {} "
            "but found {} timestamps."
        ).format(self.expected_count, self.actual_count)


class InvalidScoreException(ValidationException):
    def __init__(self, task: str, uid: int, cls: str, score) -> None:
        self.task = task
        self.uid = uid
        self.cls = cls
        self.score = score

    def __str__(self):
        return (
            "Could not deserialize {} class '{}' score to float from segment {},"
            " its value was '{}'"
        ).format(self.task, self.cls, self.uid, self.score)

class InvalidValueException(ValidationException):
    def __init__(self, v: Union[str, float], k: str, i: int, vid: str) -> None:
        self.v = v
        self.k = k
        self.i = i
        self.vid = vid

    def __str__(self):
        return f'Found invalid value {self.v} for key "{self.k}" in entry {self.i} of video {self.vid}'

class InvalidSLSException(ValidationException):
    def __init__(self, pt: int, tl: int, td: int):
        """
        Args:
            pt: Pretraining level
            tl: Training Labels level
            td: Training Data level
        """
        self.pt = pt
        self.tl = tl
        self.td = td

    def __str__(self):
        return (
            f"Invalid SLS: (PT = {self.pt}, TD = {self.td}, TL = {self.tl}). All "
            f"levels must be between 0 and 5."
        )

class InvalidModalityFlagException(ValidationException):
    def __init__(self, t_mod: int):
        """
        Args:
            t_mod: modality_flag
        """
        self.t_mod = t_mod

    def __str__(self):
        return (
            f"Invalid Modality Flag: (T_MOD = {self.t_mod}. Flag must be "
            f"between 0 and 2."
        )

def validate_submission(
        submission: Dict,
        num_interaction: int,
        valid_versions: Tuple[str, ...] = ("0.1",),
        supported_challenges: Tuple[str, ...] = (
                ("audio_based_interaction_detection",)
        ),
):
    """Validates a submission
    Parameters:
    -----------
    submission
        deserialized json containing the submission
    expected_narration_ids
        the list of narration_ids which should be present in the submission
    num_actions
        number of action predictions per test segment which should be included in the submission
    entries_to_validate
        number of entries to validate before considering the submission valid, -1 indicates all entries.
    valid_versions
        list of valid versions
    supported_challenges
        list of challenges supported by scoring program

    """

    validate_submission_version(submission, valid_versions)
    validate_submission_challenge(submission, supported_challenges)
    validate_supervision_level(submission)
    validate_modality_flag(submission)

    if "results" not in submission.keys():
        raise MissingPropertyException("results")

    task_classes = {
        "interaction": np.arange(num_interaction),
    }

    def validate_task_entry(entry, task):
        if task in entry:
            class_entry = entry[task]
            if class_entry not in task_classes[task]:
                raise InvalidClassEntry(task, class_entry)
        else:
            raise MissingPropertyException(task)

    for vid in submission['results'].keys():
        for i, entry in enumerate(submission['results'][vid]):
            validate_task_entry(entry, "interaction")
            if "score" not in entry:
                raise MissingPropertyException("score")
            if "segment" not in entry:
                raise MissingPropertyException("segment")
            if len(entry['segment'])!=2:
                raise InvalidNumberOfTimestampsException(2, len(entry['segment']))
            for k,v in entry.items():
                isnan = False
                if k=='segment':
                    isnan = np.isnan(v).any()
                elif isinstance(v, float):
                    isnan = np.isnan(v)
                else:
                    isnan = False

                if isnan:
                    raise InvalidValueException(v, k, i, vid)

def validate_submission_challenge(submission, supported_challenges):
    if "challenge" not in submission.keys():
        raise MissingPropertyException("challenge")
    if submission["challenge"] not in supported_challenges:
        raise UnsupportedChallengeException(
            supported_challenges, submission["challenge"]
        )


def validate_submission_version(submission, valid_versions):
    if "version" not in submission.keys():
        raise MissingPropertyException("version")
    if submission["version"] not in valid_versions:
        raise UnsupportedSubmissionVersionException(
            valid_versions, submission["version"]
        )


def validate_supervision_level(submission):
    sls_properties = ["sls_pt", "sls_tl", "sls_td"]
    for property in sls_properties:
        if property not in submission:
            raise MissingPropertyException(property)
    for property in sls_properties:
        if not (0 <= submission[property] <= 5):
            raise InvalidSLSException(
                pt=submission["sls_pt"],
                tl=submission["sls_tl"],
                td=submission["sls_td"],
            )

def validate_modality_flag(submission):
    if "t_mod" not in submission:
        raise MissingPropertyException("t_mod")
    if not (0 <= submission["t_mod"] <= 2):
        raise InvalidModalityFlagException(
            pt=submission["t_mod"]
        )

def print_metrics(metrics):
    for name, value in metrics.items():
        print("{name}: {value:0.2f}".format(name=name, value=value))

def read_json(path):
    with open(path, "r", encoding="utf8") as f:
        return json.load(f)


def main(args):
    logging.basicConfig(level=logging.INFO)

    groundtruth_df_path = args.path_to_annotations

    groundtruth_df: pd.DataFrame = pd.read_pickle(groundtruth_df_path)
    groundtruth_df = groundtruth_df[groundtruth_df["class"] != "background"]

    submission = read_json(args.path_to_json)

    validate_submission(
        submission, args.interaction_count, supported_challenges='audio_based_interaction_detection'
    )

    print('Submission correctly validated')

    def dump(results, maps, task):
        for i, map in enumerate(maps):
            j=i+1
            results[f"{task}_map_at_{j:02d}"] = map*100
        return results

    display_metrics = {}

    maps, avg = ANETdetection(groundtruth_df, submission).evaluate()
    dump(display_metrics, maps, "interaction")
    display_metrics[f"interaction_map_avg"] = avg*100

    for sls in ["sls_pt", "sls_tl", "sls_td", "t_mod"]:
        display_metrics[sls] = submission[sls]

    print_metrics(display_metrics)

if __name__ == "__main__":
    main(parser.parse_args())
