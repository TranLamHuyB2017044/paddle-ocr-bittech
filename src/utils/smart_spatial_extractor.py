import re
from rapidfuzz import fuzz
from src.utils.logger import Log

class SmartSpatialExtractor:
    def __init__(self, config):
        self.config = config
        # Collect all keywords to use as blockers
        # We need to know which keyword belongs to which field to avoid self-blocking
        self.field_keywords = {}
        for f, rules in config.items():
            self.field_keywords[f] = rules.get("keywords", [])

    def _get_box_center(self, box):
        """Calculate center point of a box [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]"""
        # Box is usually [TL, TR, BR, BL]
        x = sum([p[0] for p in box]) / 4
        y = sum([p[1] for p in box]) / 4
        return x, y

    def _get_box_height(self, box):
        """Estimate text height"""
        ys = [p[1] for p in box]
        return max(ys) - min(ys)
        
    def _is_text_match(self, text, keywords, threshold=0.8):
        text_lower = text.lower()
        for kw in keywords:
            # Check overlap logic if needed, but simple partial ratio is usually enough for Anchors
            if len(kw) < 3:
                if kw.lower() == text_lower: return True
                continue
                
            score = fuzz.partial_ratio(text_lower, kw.lower())
            if score >= threshold * 100:
                return True
        return False

    def _find_anchor(self, items, field_config, field_name=None):
        """Find the box that matches the label keywords or layout label"""
        # 1. Check for layout label match (highest priority)
        if field_name:
            for item in items:
                if item.get("label") == field_name:
                    Log.debug(f"[SPATIAL] Found anchor '{field_name}' by layout label")
                    return item

        keywords = field_config.get("keywords", [])
        threshold = field_config.get("keywords_threshold", 0.8)
        
        best_item = None
        best_score = 0
        
        for item in items:
            text = item.get("text", "")
            # Simple fuzzy matching
            text_lower = text.lower()
            for kw in keywords:
                # If keyword is very short, require exact match
                if len(kw) < 3:
                     if kw.lower() == text_lower:
                         score = 100
                     else: score = 0
                else:
                    score = fuzz.partial_ratio(text_lower, kw.lower())
                
                if score >= threshold * 100 and score > best_score:
                    best_score = score
                    best_item = item
        
        return best_item

    def _get_search_region(self, anchor_box, mode):
        """Define region of interest based on anchor"""
        # box: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        lbl_x_min = min(p[0] for p in anchor_box)
        lbl_x_max = max(p[0] for p in anchor_box)
        lbl_y_min = min(p[1] for p in anchor_box)
        lbl_y_max = max(p[1] for p in anchor_box)
        lbl_h = lbl_y_max - lbl_y_min
        
        # Tolerances
        y_tolerance = lbl_h * 0.7 
        
        if mode == "omni" or mode == "auto":
             # Combined Right + Below
             return {
                 "type": "omni",
                 "y_min": lbl_y_min - y_tolerance, # Start slightly above mid-line to catch misaligned text
                 "y_max": lbl_y_max + (lbl_h * 6.0), # Look down ~6 lines
                 "anchor_right": lbl_x_max,
                 "anchor_bottom": lbl_y_max,
                 "anchor_left": lbl_x_min
             }

        elif mode == "same_line":
             # Search RIGHT
             return {
                 "type": "right",
                 "y_min": lbl_y_min - y_tolerance,
                 "y_max": lbl_y_max + y_tolerance,
                 "x_min": lbl_x_max + (lbl_h * 0.2) 
             }
        
        elif mode == "next_line" or mode == "multiline":
            # Search BELOW
            return {
                "type": "below",
                "y_min": lbl_y_max + (lbl_h * 0.1),
                "y_max": lbl_y_max + (lbl_h * 5.0), 
                "x_min": lbl_x_min - (lbl_h * 2)
            }
            
        return None

    def _find_blocker_index(self, text, current_field):
        """Find the earliest index of any blocking keyword. Returns -1 if None."""
        text_lower = text.lower()
        min_idx = -1
        
        # Don't block short texts to avoid false positives?
        # Actually we should block if keyword is present.
        
        for f, keywords in self.field_keywords.items():
            if f == current_field: continue 
            
            for kw in keywords:
                if len(kw) < 4: continue 
                
                idx = text_lower.find(kw.lower())
                if idx != -1:
                    # Found a blocker
                    # Log.debug(f"[BLOCKER] Found '{kw}' in field '{current_field}' at idx {idx}. Text: {text[:20]}...")
                    if min_idx == -1 or idx < min_idx:
                        min_idx = idx
        return min_idx

    def _extract_from_region(self, items, region, anchor_box, current_field):
        if not region: return None
        
        candidates = []
        anchor_cy = self._get_box_center(anchor_box)[1]
        anchor_h = self._get_box_height(anchor_box)
        
        for item in items:
            box = item['box']
            if box == anchor_box: continue 
            
            cx, cy = self._get_box_center(box)
            
            if region["type"] == "omni":
                # Check Y range
                if region["y_min"] <= cy <= region["y_max"]:
                    # Check spatial relation
                    is_same_line = abs(cy - anchor_cy) < (anchor_h * 0.8)
                    is_below = cy > region["anchor_bottom"]
                    
                    if is_same_line:
                        # Must be to the right
                        if cx > region["anchor_right"]:
                            candidates.append(item)
                    elif is_below:
                        # Check X alignment 
                        if cx >= region["anchor_left"] - (anchor_h * 2):
                            candidates.append(item)

            elif region["type"] == "right":
                if region["y_min"] <= cy <= region["y_max"] and cx >= region["x_min"]:
                    candidates.append(item)
                    
            elif region["type"] == "below":
                if region["y_min"] <= cy <= region["y_max"]:
                    candidates.append(item)

        # Sort candidates: Top -> Bottom, Left -> Right
        candidates.sort(key=lambda x: (x['box'][0][1], x['box'][0][0]))

        # STOP AT NEXT LABEL Logic (Enhanced)
        final_texts = []
        for item in candidates:
            text = item['text']
            # Check for blockers
            idx = self._find_blocker_index(text, current_field)
            
            if idx != -1:
                # Found a blocker in this item
                # Cut text before blocker
                valid_part = text[:idx].strip()
                if valid_part:
                    final_texts.append(valid_part)
                # STOP extracting completely
                break
            else:
                final_texts.append(text)

        # Join text
        return " ".join(final_texts)

    def extract(self, items):
        """
        Main extraction function
        items: list of dict {'text', 'box', 'score'}
        """
        results = {}
        
        # Clean up items: sometimes text is empty
        items = [x for x in items if x.get('text', '').strip()]

        full_text_content = "\n".join([x['text'] for x in items])

        for field, rules in self.config.items():
            mode = rules.get("extraction_mode", "auto")
            
            # 1. Find Anchor
            anchor = self._find_anchor(items, rules, field_name=field)
            
            val = None
            if anchor:
                # 2. Define Search Region & Extract
                # "auto" now maps to "omni" (Right & Below)
                
                real_mode = mode
                if mode == "auto": real_mode = "omni"
                
                region = self._get_search_region(anchor['box'], real_mode)
                spatial_val = self._extract_from_region(items, region, anchor['box'], field) or ""
                
                # 2.1 Hybrid Stick: Check if value starts INSIDE anchor
                anchor_val = ""
                anchor_text = anchor.get('text', '')
                import re
                
                # Intelligent Split: Find the LAST keyword in text (to handle bilingual labels) and take what's AFTER it
                # "Họ tên / Full name: Nguyen Van A"
                # Keywords: "họ tên", "full name"
                # We want to split after "full name" (the one appearing last)
                
                text_lower = anchor_text.lower()
                keywords = rules.get("keywords", [])
                
                max_end_idx = -1
                
                for kw in keywords:
                    # Find all occurrences or just check existence
                    # We want the right-most keyword end position
                    # rfind is better if keyword appears multiple times, but usually keywords differ.
                    # Simple find is okay, but we want the keyword that ends LATEST in the string.
                    
                    idx = text_lower.find(kw.lower())
                    if idx != -1:
                        end_idx = idx + len(kw)
                        if end_idx > max_end_idx:
                            max_end_idx = end_idx
                            
                if max_end_idx != -1:
                    # Found at least one keyword
                    sub_after = anchor_text[max_end_idx:]
                    
                    # Remove separators (: / . -) at the start
                    sep_match = re.match(r'^[\s\.\:\/\-\|]+', sub_after)
                    if sep_match:
                        anchor_val = sub_after[sep_match.end():].strip()
                    else:
                        anchor_val = sub_after.strip()
                
                # Fallback to colon split if keyword logic failed (rare)
                if not anchor_val:
                    split_match = re.search(r'[:|]\s*(.*)$', anchor_text)
                    if split_match:
                         possible_val = split_match.group(1).strip()
                         if len(possible_val) > 0: anchor_val = possible_val
                
                # If STILL no anchor_val but it was found via YOLO label, 
                # assume the whole box is the value (common for ROI-based detect)
                if not anchor_val and anchor.get("label") == field:
                    anchor_val = anchor_text.strip()

                val = (anchor_val + " " + spatial_val).strip()
                
                # 2.2 Final Clean: Remove blockers
                cleanup_idx = self._find_blocker_index(val, field)
                if cleanup_idx != -1:
                    val = val[:cleanup_idx].strip()
                    
                # 2.3 Regex Scrubbing (The Cleaning Bullet)
                # If we have a value and a regex, extract ONLY the matching part
                # This fixes "05/12/2000 Vietnam" -> "05/12/2000"
                value_regex = rules.get("value_regex")
                if val and value_regex:
                    scrub_match = re.search(value_regex, val, re.IGNORECASE)
                    if scrub_match:
                        # Replace the messy val with the clean regex match
                        val = scrub_match.group(0).strip()
                    else:
                        # Strictly enforce regex. If it doesn't match, it's trash.
                        val = None

                # If Hybrid produced nothing, try Regex on Anchor (Fallback)
                if not val:
                    # logic remains...
                    value_regex = rules.get("value_regex")
                    if value_regex:
                         match = re.search(value_regex, anchor_text, re.IGNORECASE)
                         if match:
                             val = match.group(0).strip()
            # Useful when Label and Value are merged in one line
            
            if not val and rules.get("global_regex"):
                value_regex = rules.get("value_regex")
                if value_regex:
                    import re
                    # Use MULTILINE so ^ and $ work on lines, IGNORECASE usually good
                    match = re.search(value_regex, full_text_content, re.MULTILINE | re.IGNORECASE)
                    if match:
                        val = match.group(0).strip()

            if val:
                results[field] = val
            else:
                results[field] = None

        return results
