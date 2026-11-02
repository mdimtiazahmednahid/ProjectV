import logging
import json
import os
import datetime
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

class UIInspector:
    """
    Helps capture and analyze the Appium Android UI hierarchy.
    Crucial for debugging and adapting to Facebook UI changes.
    """
    @staticmethod
    def get_page_source(driver) -> str:
        if not driver:
            return ""
        try:
            return driver.page_source
        except Exception as e:
            logger.error(f"Error getting page source: {e}")
            return ""
            
    @staticmethod
    def parse_xml_to_nodes(xml_source: str):
        nodes = []
        try:
            root = ET.fromstring(xml_source)
            for elem in root.iter():
                # Elements in Android hierarchy usually have 'node' tag
                if elem.tag == 'hierarchy':
                    continue
                    
                node_info = {
                    "class": elem.attrib.get('class', ''),
                    "text": elem.attrib.get('text', ''),
                    "content-desc": elem.attrib.get('content-desc', ''),
                    "resource-id": elem.attrib.get('resource-id', ''),
                    "clickable": elem.attrib.get('clickable', 'false') == 'true',
                    "enabled": elem.attrib.get('enabled', 'false') == 'true',
                    "focusable": elem.attrib.get('focusable', 'false') == 'true',
                    "scrollable": elem.attrib.get('scrollable', 'false') == 'true',
                    "selected": elem.attrib.get('selected', 'false') == 'true',
                    "heading": elem.attrib.get('heading', 'false') == 'true',
                    "bounds": elem.attrib.get('bounds', ''),
                    "package": elem.attrib.get('package', '')
                }
                nodes.append(node_info)
        except Exception as e:
            logger.error(f"Failed to parse XML source: {e}")
            
        return nodes
        
    @staticmethod
    def save_inspection(xml_source: str, save_dir: str = "data/inspections"):
        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        xml_path = os.path.join(save_dir, f"page_source_{timestamp}.xml")
        json_path = os.path.join(save_dir, f"nodes_{timestamp}.json")
        
        try:
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_source)
                
            nodes = UIInspector.parse_xml_to_nodes(xml_source)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(nodes, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Saved inspection to {save_dir} with timestamp {timestamp}")
            return xml_path, json_path
        except Exception as e:
            logger.error(f"Error saving inspection: {e}")
            return None, None
