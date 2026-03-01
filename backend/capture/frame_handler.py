from __future__ import annotations

from uuid import uuid4

from loguru import logger

from identification.human_detector import HumanDetector


class FrameHandler:
    """Process incoming stream frames through the detection pipeline."""

    def __init__(self):
        self.detector = HumanDetector()
        self._seen_tracks: set[int] = set()
        logger.info("FrameHandler initialized")

    async def process_frame(
        self,
        frame_b64: str,
        timestamp: int,
        source: str = "glasses_stream",
    ) -> dict:
        capture_id = f"cap_{uuid4().hex[:12]}"

        # Step 1: Detect humans
        result = self.detector.detect_from_base64(frame_b64)
        detections = result["detections"]

        # Step 2: Identify new tracks (persons not seen before)
        new_detections = []
        for det in detections:
            tid = det.get("track_id")
            if tid is not None and tid not in self._seen_tracks:
                self._seen_tracks.add(tid)
                new_detections.append(det)

        # Step 3: Crop new persons for face pipeline
        if new_detections:
            crops = self.detector.crop_persons(frame_b64, new_detections)
            logger.info(f"New persons detected: {len(crops)} crop(s) ready for face pipeline")
            # TODO: Forward crops to face identification pipeline
            # await self.face_pipeline.identify(crops)

        return {
            "capture_id": capture_id,
            "detections": detections,
            "new_persons": len(new_detections),
            "timestamp": timestamp,
            "source": source,
        }
