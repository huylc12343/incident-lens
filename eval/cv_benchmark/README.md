# CV recall benchmark

`annotations.json` is a small, manually reviewed, every-10th-frame subset from both bundled videos. The plate regions are conservative redaction regions around the visible plate area. The source videos do not contain clearly resolvable faces, so the face denominator is zero and face recall is reported as `N/A`.

This subset is useful for regression and before/after comparisons. It is not enough to claim production-grade privacy. Before deployment, add at least 100-200 independently labelled frames, including front/rear/side views, occlusions, night/rain, close/far objects, and frames with visible faces.

The complete measured comparison, model verdict, and bounded tracking policy are in [`docs/CV_VALIDATION_REPORT.md`](../../docs/CV_VALIDATION_REPORT.md).
