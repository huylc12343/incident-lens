**PLAN_EVAL.md — IncidentLens Evaluation Specification**  
   
    
   
  **0. Mục tiêu tài liệu**  
   
  Agent coding phải bám đúng các quy ước dưới đây và **không tự đoán thêm field, không tự đổi schema, không tự đổi logic chấm điểm**.  
   
    
   
  Phạm vi đánh giá gồm 3 thành phần:  
1. VLM  
2. LLM_verifi  
3. LLM_report  
   
  Các thành phần này được gọi trực tiếp từ src/, tuyệt đối không được tạo mới  
   
  Trong mỗi thành phần, metric được chia thành:  
- CODE: tính hoàn toàn bằng code từ structured output + ground truth.  
- LLM + CODE: LLM chỉ làm semantic extraction / semantic judging; sau đó CODE tính metric cuối.  
   
  ![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAnEAAAACCAYAAAA3pIp+AAAABmJLR0QA/wD/AP+gvaeTAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAANElEQVR4nO3OMQ0AIAwAwZKgBKWVgjV8dGDBABMhuZt+/JaZIyJmAADwi9VP1NMNAABu1AaU5AUhGCVyvwAAAABJRU5ErkJggg==)  
**1. Ground Truth chung**  
   
  Golden label CARLA có dạng tối thiểu:  
  {  
     "sample_id": "CARLA_INC_CUT_IN_000011_D4928379_13ADAB0E"  
     "is_incident": true,  
     "incident_type": "side_collision",
     "timeline": {  
       "t_start": 10.0,  
       "t0": 10.65,  
       "t_end": 12.05  
     },  
     "evaluation_events": [  
       {  
         "event_type": "cut_in_started"   
         "timestamp": 10.0  
       },  
       {   
         "event_type": "collision",  
         "timestamp": 10.65  
       }  
     ]  
   }  
   
    
  ![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAnEAAAACCAYAAAA3pIp+AAAABmJLR0QA/wD/AP+gvaeTAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAANklEQVR4nO3OMQ2AABAAsSNhxgCu0MPwOlGADCywEZJWQZeZ2aszAAD+4l6rrTq+ngAA8Nr1AKK/BD8rWFUhAAAAAElFTkSuQmCC)  
   
  **3. OUTPUT MODEL CỦA TỪNG NODE ** **TRONG ** **SRC/**   
   
   Phần này là bắt buộc để agent coding biết chính xác lấy dữ liệu ở đâu.  
   
  **3.1. VLM output model**  
   
  Structured output  
   
  {  
     "global_scene": "string",  
     "video_summary": "string | null",  
    “"vlm_has_accident": false/true  
     "incident_window": {  
       "t_start": 0.0,  
        "t0": 0.0,   
       "t_end": 44.8  
    “”  
    },   
     "representative_timestamp_s": 14.0,  
     "timeline": [  
       {  
         "timestamp_s": 14.0,  
         "description": "string",  
         "evidence_ids": ["frame-000020"]  
       }  
     ],  
     "claims": [  
       {  
        "claim_id": "claim_1",  
         "text": "string",  
         "timestamp_s": 14.0,  
         "evidence": [  
           {  
             "evidence_id": "frame-000020",  
             "timestamp_s": 14.1867  
           }  
         ],  
         "verification_status": "unverified"  
       }  
     ]   
   }  
   
  **3.2. LLM_verifi output model**  
   
   
  Verifier output  
   
  {  
     "has_accident": true,  
     "results": [  
       {  
         "claim_id": "claim_1",  
         "status": "supported",  
         "reason": "string",  
         "evidence_ids": [  
           "log-row:10.8",  
           "log-row:14",  
           "log-row:17.2"  
         ]  
       }  
     ]  
   }  
   
  Các enum hợp lệ:  
  status:  
   - supported  
   - contradicted  
   - unverified  
  **3.3. LLM_report output model**  
   
  Report output:  
  {  
     "type_of_accident": "no_incident",  
     "incident_window": {  
       "t_start": 0.0,  
       "t0": 0.0,  
       "t_end": 44.8  
     },  
     "representative_timestamp_s": 14.0,  
     "timeline": "string",  
     "video_observations": "string",  
     "hypothesized_causes": "string"  
   }  
   
    
  type_of_accident thuộc enum:  
  rear_end_collision  
   crossing_collision  
   side_collision  
   head_on_collision  
   pedestrian_collision  
   static_object_collision  
   roadside_collision  
   no_incident  
   other_unknown  
  Rule production hiện tại:  
  verification.has_accident = false  
   → report.type_of_accident phải là no_incident  
   verification.has_accident = true  
   → report.type_of_accident phải khác no_incident  
   
    
  **4. VLM — CODE METRICS**  
   
   **4.1. VLM Median t0 Error**  
   
  **Loại**  
  CODE  
   
  **Ý nghĩa**  
  Đo VLM xác định **thời điểm chính của tai nạn** lệch bao nhiêu giây.  
   
  **Prediction field**  
  vlm_output.incident_window.t0  
  **Gold field**  
  label.timeline.t0  
  **Điều kiện tính**  
  Chỉ tính sample khi có tai nạn tức:  
   vlm_output.incident_window.t0 != 0  
   
  **Công thức từng sample**  
   
  t0_error = abs(pred_t0 - gold_t0)  
   
  **Aggregate**  
  median_t0_error = median(all_valid_t0_errors)  
  **Output evaluator**  
  {  
      "vlm_median_t0_error_s": 0.25,  
     "num_samples_used": 18   
   }  
  **4.2. VLM Temporal IoU**  
   
  **Loại**  
  CODE  
  **Ý nghĩa**  
  Đo VLM khoanh đúng **khoảng thời gian incident** đến đâu.  
  **Prediction**  
  pred_start = vlm_output.incident_window.t_start  
   pred_end   = vlm_output.incident_window.t_end  
  **Gold**  
  gold_start = label.timeline.t_start  
   gold_end   = label.timeline.t_end  
  **Điều kiện tính**  
  Chỉ tính khi có tai nạn:  
 vlm_output.incident_window.t0 != 0  
  **Công thức**  
  intersection = max(  
       0.0,  
       min(pred_end, gold_end) - max(pred_start, gold_start)  
   )  
   union = max(pred_end, gold_end) - min(pred_start, gold_start)  
   iou = intersection / union if union > 0 else 0.0  
  **Ý nghĩa**  
  1.0 = khớp hoàn toàn  
   0.0 = không chồng nhau  
  **Aggregate**  
  Báo ít nhất:  
  Mean Temporal IoU  
   Median Temporal IoU  
  **Output evaluator**  
  {  
     "vlm_temporal_iou_mean": 0.72,  
     "vlm_temporal_iou_median": 0.76  
   }  
   
  **4.3. Event Timestamp MAE**  
   
  **Loại**  
  CODE  
  **Ý nghĩa**  
  Sau khi Gold Event Recall đã match được event nào của VLM tương ứng với event nào của ground truth, đo timestamp lệch trung bình bao nhiêu giây.  
  **Input bắt buộc**  
   
   Kết quả semantic matching phải có dạng:  
   
  {  
   
     "matches": [  
       {  
         "gold_event_index": 2,  
         "pred_event_index": 1,  
         "gold_event_type": "collision",  
         "gold_timestamp": 10.65,  
         "pred_timestamp": 10.80  
       }  
     ]  
   }  
   
  **Công thức**  
  errors = [  
       abs(match["pred_timestamp"] - match["gold_timestamp"])  
       for match in matches  
   ]  
   mae = sum(errors) / len(errors)  
  **Điều kiện**  
  Chỉ tính trên semantic match hợp lệ.  
  Nếu không có match nào:  
  MAE = null  
   num_matches = 0  
  Không tự gán MAE = 0.  
   
  **Output**  
  {  
     "event_timestamp_mae_s": 0.18,  
     "num_matched_events": 14  
   }  
  **4.** **4** **. VLM Incident Precision / Recall / F1**  
   
  **Loại**  
 CODE  
   
  **Ý nghĩa**  
  Đo riêng VLM có đang kết luận đúng:  
  có incident / không incident  
  hay không.  
  VLM có trả về   
  {  
     "vlm_has_accident": False  
   }  
   
  **CODE sau extractor**  
  pred = extracted["vlm_has_accident"]  
   gold = label["is_incident"]  
  Tạo:  
  TP = pred=true  & gold=true  
   FP = pred=true  & gold=false  
   FN = pred=false & gold=true  
   TN = pred=false & gold=false  
  **Công thức**  
  precision,  recall,   f1    
   
  **Output**  
  {  
     "vlm_incident_precision": 0.91,  
     "vlm_incident_recall": 0.87,  
     "vlm_incident_f1": 0.89,  
     "tp": 20,  
     "fp": 2,  
     "fn": 3,  
     "tn": 15  
   }  
 **6. LLM_VERIFI — CODE METRICS**  
   
   
  **6.1. Verifier Incident Precision / Recall / F1**  
   
  **Loại**  
   
  CODE  
   
  **Ý nghĩa**  
    
  Đây là metric binary incident quan trọng nhất của pipeline sau khi kết hợp VLM + telemetry.  
   
  **Prediction**  
  verification.has_accident  
  **Gold**  
  label.is_incident  
  **Công thức**  
  Giống VLM Incident F1:  
  TP  
   FP  
   FN  
   TN  
   Precision  
   Recall  
   F1  
  **Output**  
  {  
     "verifier_incident_precision": 0.95,  
     "verifier_incident_recall": 0.93,   
     "verifier_incident_f1": 0.94  }  
  **Báo thêm để so sánh pipeline**  
   
   vlm_incident_f1  
   verifier_incident_f1  
   
  Mục tiêu:  
  Verifier tốt hơn hoặc ít nhất không làm giảm đáng kể VLM.  
   
   
  **6.2. Evidence ID Validity**  
   
  **Loại**  
  CODE  
   
  **Ý nghĩa**  
  Kiểm tra verifier có bịa hoặc dùng evidence ID ngoài phạm vi backend cấp không.  
  **Input**  
  Per claim:  
  verification_item.allowed_evidence_ids  
   verification_result.evidence_ids  
  **Logic**  
  Mỗi predicted ID phải nằm trong allowed set:  
  valid = evidence_id in allowed_evidence_ids  
  **Cách tính khuyến nghị**  
  Tính cả:  
  evidence_id_precision  
   claim_evidence_validity_rate  
  ***Evidence ID Precision***  
  valid_ids / all_predicted_ids  
  ***Claim Evidence Validity Rate***  
  Một claim pass khi:  
  mọi evidence_id của claim đều hợp lệ  
  valid_claims / all_claims  
  **Special case**  
  Nếu:  
  predicted evidence_ids = []  
  thì không đưa vào denominator của evidence_id_precision.  
  Nhưng claim vẫn pass structural validity nếu empty list được phép.  
   
  **Output**  
  {  
     "evidence_id_precision": 1.0,  
     "claim_evidence_validity_rate": 1.0,  
     "invalid_evidence_ids": []  
   }  
  **6.**  **3**  **. Evidence ID Validity**  
  Thống kê tỉ lệ %  
   supported  
  contradicted  
  unverified  
 output  
  {  
     "supported": 1.0,  
     "contradicted": 1.0,  
     "unverified": []  
   }  
  **8. LLM_REPORT — CODE METRICS**  
   
  **8.1. Report Decision Consistency**  
   
  **Loại**  
   
  CODE  
   
  **Ý nghĩa**  
  Kiểm tra report có tuân thủ quyết định verification.has_accident hay không.  
   
  **Prediction fields**  
  verification.has_accident  
   report.type_of_accident  
  **Rule**  
  if verification_has_accident is False:  
       pass_case = report_type == "no_incident"  
   if verification_has_accident is True:  
       pass_case = report_type != "no_incident"  
  Nếu verification.has_accident is null:  
  sample không tính metric này  
   và phải log evaluator warning  
  **Công thức**  
  consistency = passed_samples / eligible_samples  
  **Output**  
  {  
     "report_decision_consistency": 1.0,  
     "passed": 40,  
     "eligible": 40  
   }  
  **Không dùng Final Incident F1**  
  Không tính thêm Final Incident F1 vì report đang bị ràng buộc bởi verification.has_accident.  
  Nếu report tuân thủ prompt thì Final Incident F1 chỉ lặp lại Verifier Incident F1.  
   
  **8.2. Final Median t0 Error**  
   
  **Loại**  
  CODE  
   
  **Ý nghĩa**  
  Đo timestamp incident cuối cùng sau report lệch ground truth bao nhiêu.  
   
  **Prediction**  
  report.incident_window.t0  
  **Gold**  
  label.timeline.t0  
  **Điều kiệ** **n ** **tương ** **tự ** **vlm**  
  **Công thức**  
  error = abs(report_t0 - gold_t0)  
   median_error = median(errors)  
  **Output**  
  {  
     "report_median_t0_error_s": 0.20  
   }  
   
    
  **Nên so với VLM**  
  vlm_median_t0_error_s  
 report_median_t0_error_s  
   
  Không tạo metric "improvement" tổng hợp nếu chưa cần; chỉ hiển thị side-by-side.  
   
  **8.3. Final Temporal IoU**  
   
  **Loại**  
  CODE  
   
  **Ý nghĩa**  
  Đo incident window của report khớp ground truth đến đâu.  
   
  **Prediction**  
  report.incident_window.t_start  
   report.incident_window.t_end  
  **Gold**  
  label.timeline.t_start  
   label.timeline.t_end  
  **Điều kiện**  
  Giống Final t0 Error.  
  **Công thức**  
  Dùng cùng Temporal IoU function của VLM.  
  **Output**  
  {  
     "report_temporal_iou_mean": 0.78,  
     "report_temporal_iou_median": 0.81  
   }  
  **8.3. ** **type ** **of **incident  
   
 **Loại**  
  CODE  
   
  **Ý nghĩa**  
  Đo incident_type của report có phân loại tai nạn đúng không  
  **Prediction**  
report  
  **Gold**  
   label.incident_type  
 **Điều kiện**  
 Không có **  
 Công thức**  
  prediction, f1, recall  
   
  **12. CẤU HÌNH EVALUATOR PHẢI ĐẶT CỐ ĐỊNH**  
   
    
   
  Kiến trúc thư mục data goldent set dự kiến  
   
  Thư mục golden set cùng cấp với thư mục eval/, src/  
  golden_set/  
   
 │  
   
 ├── Data_001/  
   
 │   ├── input/  
   
 │   │   ├── .mp4  
   
 │   │   └── .csv  
   
 │   │  
   
 │   └── labels/  
   
 │       └── .json  
   
 │  
   
 ├── Data_002/  
   
 │   ├── input/  
   
 │   │   ├── .mp4  
   
 │   │   └── .csv  
   
 │   │  
   
 │   └── labels/  
   
 │       └── .json  
   
 │  
   
 ├── Data_003/  
   
 │   ├── input/  
   
 │   │   ├── .mp4  
   
 │   │   └── .csv  
   
 │   │  
   
 │   └── labels/  
   
 │       └── .json  
   
 │  
   
 └── ...  
