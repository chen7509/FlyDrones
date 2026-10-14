# GPL diagnostic patches

`openvins_feature_trace.patch` is a diagnostic derivative of OpenVINS commit
`69488123ed9362dd44b6f28e7f4680abbff1442b` and is distributed under
GPL-3.0-or-later, matching the upstream files it modifies.  It is applied only
to an isolated research build.  The FlyDrones runtime does not apply or load
this patch in normal operation.

`openvins_feature_history_geometry.patch` is an incremental diagnostic patch
for the same pinned OpenVINS commit after `openvins_feature_trace.patch`.  It
records candidate provenance, clone-window pruning, and read-only
triangulation geometry.  It is also GPL-3.0-or-later and is used only by the
isolated fixed-input research build; it does not change estimator thresholds
or enable any FlyDrones runtime path.

`openvins_dataset_consumer.cpp` and `openvins_dataset_io.h` are prospective
GPL-3.0-or-later research adapters for the same pinned OpenVINS API. Their
declared 2 GiB admission refused before compilation; they are uncompiled and
unvalidated, and do not enable a flight or training path. The independent
build-free study uses the byte-exact GPL runner/source already archived in
`evidence/openvins-offline-1701.zip`, launched out of process. It consumes PPM
decoded to grayscale, not the prospective adapter's PNG interface. The pinned
upstream license is preserved with the study evidence.
