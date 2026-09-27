# Five-camera render-capacity amendment 7

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-211315/` timed out
while closing the temporary renderer witness. Its log continued to receive five
streams near 10 Hz. Early image callbacks were not guaranteed to start at the
same local sequence number as trigger callbacks, so the witness's temporary
`(vehicle, sequence)` pending set could never become empty even after later
trigger/image pairs were complete.

## Binding correction

1. After the fixed completion drain interval, close only after the last
   processed transport event is an image and the callback queue is empty. This
   avoids cutting between a trigger and its following image without assuming
   that independently counted callback sequences share an origin.
2. Always generate the witness summary after this bounded close. Historical
   missing or unmatched events remain visible and are rejected by the renderer
   witness integrity gate; they must not be converted into a timeout.
3. Add a regression with a deliberately dropped post-completion image followed
   by a continuing stream. It must close with an integrity rejection and a
   preserved summary rather than hanging.
4. Restart all Task 6 development checks with new identifiers.

No scored phase arithmetic, renderer acceptance, camera configuration, or
performance threshold changes.
