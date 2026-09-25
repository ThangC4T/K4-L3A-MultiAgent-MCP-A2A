# L3A Architecture Record

## 1. System overview

Hệ thống xử lý khiếu nại thương mại điện tử (K4 L3A) áp dụng mô hình phân cấp **Coordinator — Specialist Agents — Verifier**:

```text
               inputs/<case_id>.json
                         │
                         ▼
                 [CoordinatorAgent]
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   [OrderAgent]   [PaymentAgent]   [ShipmentAgent]
        │                │                │
        └────────────────┼────────────────┘
                         ▼ (Evidence + Findings)
                  [PolicyAgent]
                         │
                         ▼ (Draft Output)
                  [VerifierAgent] (Invariants Check)
                         │
                         ▼
               outputs/<case_id>.json & traces/trace.jsonl
```

- **CoordinatorAgent**: Tiếp nhận case, trích xuất mã thực thể (`order_id`, `customer_id`), điều phối luồng làm việc và phát sinh các trace lifecycle events (`task_assigned`, `handoff`).
- **Specialist Agents (Order, Payment, Shipment)**: Chỉ truy vấn các công cụ MCP thuộc domain phụ trách, trích xuất dữ liệu xác thực (ground truth), thu thập `evidence_ref` và ghi vết `tool_result_consumed`.
- **PolicyAgent**: Đánh giá toàn diện bằng chứng, phân loại 11 mã sự cố chuẩn (`primary_issue`), phân định trách nhiệm (`responsible_parties`), tính toán tiền hoàn BRL và đề xuất hành động.
- **VerifierAgent**: Đóng vai trò gác cổng kiểm tra toàn bộ invariants (Schema, tiền tệ, logic status, quyền sở hữu bằng chứng) trước khi finalize.

---

## 2. Agent ownership & Tool Permissions

| Actor | Input | Trách nhiệm | MCP Tools được phép | Output / Handoff |
| :--- | :--- | :--- | :--- | :--- |
| **Coordinator** | `inputs/<case_id>.json` | Phân tích input, điều phối A2A workflow | Không gọi MCP trực tiếp | `CaseState` chuyển giao cho các Specialist |
| **Order/Item Agent** | `CaseState` (chứa `order_id`) | Xác thực trạng thái đơn, danh sách mặt hàng, người bán, bối cảnh sản phẩm | `get_order`, `get_order_items`, `get_sellers`, `get_product_context` | `order_data`, `items_data`, `seller_ids`, `item_ids`, `evidence_refs` |
| **Payment Agent** | `CaseState` | Đối soát giao dịch, phát hiện charge trùng lặp, chia tách thanh toán (split), tiến trình hoàn tiền | `get_order_payments`, `get_payment_timeline`, `get_refund_timeline` | `payments_data`, `payment_timeline`, `refund_timeline`, `payment_references` |
| **Shipment Agent** | `CaseState` | Đối soát SLA giao hàng: thời hạn seller gửi hàng vs carrier, ngày giao dự kiến vs thực tế | `get_shipment_summary` | `shipment_summary`, `shipment_ids`, SLA delay metrics |
| **Policy Agent** | `CaseState` tổng hợp | Đọc chính sách sàn, phân loại primary_issue, xác định nguyên nhân gốc, tính toán tiền hoàn | `get_policy` | Dự thảo output (`draft_output`), `policy_decided` trace |
| **Verifier** | `draft_output`, `CaseState` | Kiểm tra cross-field invariants, tính nhất quán tài chính, thẩm định nguồn gốc evidence, JSON Schema | Không gọi MCP | Final output JSON chuẩn `day09-l3a-output-v2` |

---

## 3. A2A Protocol

- **State Container**: Đối tượng `CaseState` lưu trữ toàn bộ trạng thái điều tra độc lập theo từng `case_id`. Tuyệt đối không chia sẻ trạng thái giữa các case.
- **Correlation**: Mọi event và MCP call đều mang `case_id` tương ứng làm correlation key.
- **Message Handoff**: Handoff tuần tự một chiều (Directed Acyclic Graph):
  `Coordinator` $\rightarrow$ `OrderAgent` $\rightarrow$ `PaymentAgent` $\rightarrow$ `ShipmentAgent` $\rightarrow$ `PolicyAgent` $\rightarrow$ `VerifierAgent`.
- **Chống lặp (Loop Prevention)**: Luồng xử lý là pipeline đơn hướng, mỗi agent chỉ thực thi 1 lần trên mỗi case, không có cơ chế gọi vòng lặp ngược (no backward cycle).
- **Trace Observability**: Chỉ ghi nhận các sự kiện quan sát được: `case_received`, `task_assigned`, `tool_result_consumed`, `handoff`, `policy_decided`, `verification_completed`, `case_finalized`. Không log prompt thô hoặc suy luận nội bộ (chain-of-thought).

---

## 4. Evidence Lifecycle

1. **Discovery & Call**: Agent gọi MCP Gateway qua HTTP Streamable với session được chứng thực bởi Team API Key.
2. **Envelope Validation**: Dữ liệu phản hồi được validate ngay lập tức với `mcp-evidence-response-v1.schema.json`.
3. **Registration**: Trích xuất `evidence_ref` (định dạng `^ev_[A-Za-z0-9_-]{20,96}$`) và lưu vào danh sách `state.evidence_refs`.
4. **Audit Trace Linkage**: Ngay sau khi tiêu thụ bằng chứng, agent phát sự kiện `tool_result_consumed` đính kèm đúng `evidence_refs` và `tool_name`.
5. **Output Scoping**: Verifier lọc chỉ giữ lại những `evidence_ref` thực sự được thu thập từ MCP trong case hiện tại (tối đa 30 refs). Cấm dùng lại evidence giữa các case.

---

## 5. Failure Policy

| Failure Scenario | Retry? | Fallback Strategy | Trace Event / Code |
| :--- | :---: | :--- | :--- |
| **MCP Timeout** | Có (tối đa 2 lần, exponential backoff) | Ghi nhận thiếu bằng chứng, tiếp tục điều tra các domain khác | `tool_result_consumed` / `TIMEOUT_SKIPPED` |
| **Entity Not Found (404)** | Không | Phân loại `insufficient_evidence` nếu thiếu order bắt buộc | `policy_decided` / `MISSING_AUTHORITATIVE_DATA` |
| **Data Conflict** | Không | Ưu tiên dữ liệu từ MCP authoritative DB so với customer claims; ghi nhận vào `data_conflicts` | `policy_decided` / `CONFLICT_RESOLVED_BY_AUTHORITY` |
| **Invalid Specialist Result** | Không | Sử dụng giá trị an toàn mặc định (fallback to safe defaults), giảm confidence | `verification_completed` / `INVARIANT_AUTO_REPAIRED` |

---

## 6. Verification Invariants

Trước khi xuất kết quả cuối cùng, `VerifierAgent` thực thi các kiểm tra bắt buộc:
1. **Schema Compliance**: Toàn bộ object khớp 100% với JSON Schema `day09-l3a-output-v2`.
2. **Consistency Invariants**:
   - Nếu `case_status == "no_action"`, thì `recommended_refund_brl == 0.0` và `refund_lines` rỗng.
   - Nếu `case_status == "action_required"`, thì `recommended_refund_brl` bằng tổng `amount_brl` trong các `refund_lines`.
   - `resolution_actions` không được rỗng, không trùng lặp và tối đa 8 hành động.
3. **Evidence Provenance**: Toàn bộ `evidence_refs` trong output phải là tập con của các refs đã thu thập từ MCP Gateway trong case này.
4. **Responsible Party Alignment**: Bên chịu trách nhiệm phải logic với `primary_issue` (ví dụ: `late_delivery_seller` gán trách nhiệm cho `seller`, `late_delivery_logistics` gán cho `logistics_provider`).
5. **Confidence Calibration**: Điểm tin cậy được căn chỉnh theo mức độ đầy đủ của bằng chứng (từ 0.60 đến 0.95).

---

## 7. Reproducibility

- **Runtime**: Python 3.11.9 trên Windows/Linux.
- **Dependencies**: Được cố định tại `pyproject.toml` (`httpx2>=2,<3`, `mcp>=2,<3`, `jsonschema>=4.25,<5`, `python-dotenv>=1.1,<2`).
- **Concurrency**: Thực thi tuần tự hoặc batch async đảm bảo không vượt quá budget gọi MCP.
- **Lệnh thực thi**:
  - Kiểm tra input: `day09 validate-inputs`
  - Liệt kê MCP tools: `day09 mcp-tools`
  - Chạy toàn bộ case: `day09 run`
  - Kiểm tra output và trace: `day09 validate`
  - Đóng gói nộp bài: `day09 package --output dist/submission.zip`
