import csv
import logging
import os
from typing import List
from app.models.share_profile import ShareProfile, ContestParticipant

logger = logging.getLogger(__name__)

class CSVExporter:
    @staticmethod
    def export(profiles: List[ShareProfile], output_path: str):
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
            # UTF-8 with BOM for Excel compatibility
            with open(output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = [
                    'Name', 'Action', 'Profile URL', 'Share URL', 'Content', 'Reactions', 'Comments', 'Confidence', 
                    'Source', 'First Seen', 'Last Seen', 'Session ID'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for profile in profiles:
                    writer.writerow({
                        'Name': profile.name,
                        'Action': getattr(profile, 'action_type', 'share'),
                        'Profile URL': profile.profile_url or "",
                        'Share URL': profile.share_url or "",
                        'Content': profile.content or "",
                        'Reactions': profile.reactions or "0",
                        'Comments': profile.comments or "0",
                        'Confidence': f"{profile.confidence:.2f}",
                        'Source': profile.source,
                        'First Seen': profile.first_seen_at,
                        'Last Seen': profile.last_seen_at,
                        'Session ID': profile.session_id
                    })
            logger.info(f"Successfully exported {len(profiles)} profiles to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export CSV to {output_path}: {e}")
            return False

    @staticmethod
    def export_contest(participants: List[ContestParticipant], output_path: str):
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = [
                    'Serial #', 'Name', 'Eligible', 'Actions Completed', 'Liked', 'Commented', 'Shared',
                    'Status', 'Comments Text', 'Share Content', 'Profile URL', 'Avatar Hash', 'First Seen'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for p in participants:
                    is_qual = getattr(p, "_eval_is_qualified", p.is_eligible)
                    status_str = getattr(p, "_eval_status_badge", None) or p.status_label
                    writer.writerow({
                        'Serial #': p.serial_code,
                        'Name': p.display_name,
                        'Eligible': 'YES' if is_qual else 'NO',
                        'Actions Completed': f"{p.actions_completed}/3",
                        'Liked': 'Yes' if p.liked else 'No',
                        'Commented': 'Yes' if p.commented else 'No',
                        'Shared': 'Yes' if p.shared else 'No',
                        'Status': status_str,
                        'Comments Text': " | ".join(p.comment_texts),
                        'Share Content': " | ".join(p.share_contents),
                        'Profile URL': p.profile_url or "",
                        'Avatar Hash': p.avatar_hash or "",
                        'First Seen': p.first_seen_at,
                    })
            logger.info(f"Successfully exported {len(participants)} contest participants to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export contest CSV to {output_path}: {e}")
            return False
