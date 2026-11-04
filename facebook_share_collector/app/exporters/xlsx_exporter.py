import logging
import os
from typing import List
from app.models.share_profile import ShareProfile, ContestParticipant

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

logger = logging.getLogger(__name__)

class XLSXExporter:
    @staticmethod
    def export(profiles: List[ShareProfile], output_path: str):
        if not OPENPYXL_AVAILABLE:
            logger.error("openpyxl is not installed. Cannot export to XLSX.")
            return False
            
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wb = Workbook()
            ws = wb.active
            ws.title = "Facebook Shares"
            
            headers = [
                'Name', 'Profile URL', 'Shared Post URL', 'Share URL', 'Content', 'Reactions', 'Comments', 'Confidence', 
                'Source', 'First Seen', 'Last Seen', 'Session ID'
            ]
            
            # Write headers
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
                
            # Freeze panes
            ws.freeze_panes = "A2"
            
            # Write data
            for row, profile in enumerate(profiles, 2):
                ws.cell(row=row, column=1, value=profile.name)
                ws.cell(row=row, column=2, value=profile.profile_url or "")
                ws.cell(row=row, column=3, value=getattr(profile, "shared_post_url", None) or "")
                ws.cell(row=row, column=4, value=profile.share_url or "")
                ws.cell(row=row, column=5, value=profile.content or "")
                ws.cell(row=row, column=6, value=profile.reactions or "0")
                ws.cell(row=row, column=7, value=profile.comments or "0")
                ws.cell(row=row, column=8, value=profile.confidence)
                ws.cell(row=row, column=9, value=profile.source)
                ws.cell(row=row, column=10, value=profile.first_seen_at)
                ws.cell(row=row, column=11, value=profile.last_seen_at)
                ws.cell(row=row, column=12, value=profile.session_id)
                
            # Autofilter
            ws.auto_filter.ref = ws.dimensions
            
            # Adjust column widths roughly
            ws.column_dimensions['A'].width = 30
            ws.column_dimensions['B'].width = 50
            ws.column_dimensions['C'].width = 50
            ws.column_dimensions['D'].width = 12
            
            wb.save(output_path)
            logger.info(f"Successfully exported {len(profiles)} profiles to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export XLSX to {output_path}: {e}")
            return False

    @staticmethod
    def export_contest(participants: List[ContestParticipant], output_path: str):
        if not OPENPYXL_AVAILABLE:
            logger.error("openpyxl is not installed. Cannot export to XLSX.")
            return False

        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wb = Workbook()
            ws = wb.active
            ws.title = "Contest Validation"

            headers = [
                'Serial #', 'Name', 'Eligible', 'Actions Completed', 'Liked', 'Reaction Type', 'Commented', 'Shared',
                'Status', 'Comments Text', 'Share Content', 'Profile URL', 'Shared Post URL', 'Avatar Hash', 'First Seen'
            ]
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')

            ws.freeze_panes = "A2"

            for row, p in enumerate(participants, 2):
                is_qual = getattr(p, "_eval_is_qualified", p.is_eligible)
                status_str = getattr(p, "_eval_status_badge", None) or p.status_label
                liked_val = f"Yes ({p.combined_reactions})" if (p.liked and getattr(p, "reaction_types", None)) else ('Yes' if p.liked else 'No')
                ws.cell(row=row, column=1, value=p.serial_code)
                ws.cell(row=row, column=2, value=p.display_name)
                ws.cell(row=row, column=3, value='YES' if is_qual else 'NO')
                ws.cell(row=row, column=4, value=f"{p.actions_completed}/3")
                ws.cell(row=row, column=5, value=liked_val)
                ws.cell(row=row, column=6, value=p.combined_reactions if getattr(p, "reaction_types", None) else ("Reacted" if p.liked else ""))
                ws.cell(row=row, column=7, value='Yes' if p.commented else 'No')
                ws.cell(row=row, column=8, value='Yes' if p.shared else 'No')
                ws.cell(row=row, column=9, value=status_str)
                ws.cell(row=row, column=10, value=" | ".join(p.comment_texts))
                ws.cell(row=row, column=11, value=" | ".join(p.share_contents))
                ws.cell(row=row, column=12, value=p.profile_url or "")
                ws.cell(row=row, column=13, value=" | ".join(getattr(p, "shared_post_urls", [])))
                ws.cell(row=row, column=14, value=p.avatar_hash or "")
                ws.cell(row=row, column=15, value=p.first_seen_at)

            ws.auto_filter.ref = ws.dimensions
            ws.column_dimensions['A'].width = 28
            ws.column_dimensions['B'].width = 12
            ws.column_dimensions['C'].width = 18
            ws.column_dimensions['G'].width = 32
            ws.column_dimensions['H'].width = 40
            ws.column_dimensions['I'].width = 40
            ws.column_dimensions['J'].width = 45

            wb.save(output_path)
            logger.info(f"Successfully exported {len(participants)} contest participants to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export contest XLSX to {output_path}: {e}")
            return False
