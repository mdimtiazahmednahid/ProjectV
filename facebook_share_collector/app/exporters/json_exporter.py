import json
import logging
import os
from typing import List
from app.models.share_profile import ShareProfile

logger = logging.getLogger(__name__)

class JSONExporter:
    @staticmethod
    def export(profiles: List[ShareProfile], output_path: str):
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            data = [p.to_dict() for p in profiles]
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Successfully exported {len(profiles)} profiles to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export JSON to {output_path}: {e}")
            return False
