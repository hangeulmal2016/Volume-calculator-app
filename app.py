import streamlit as pd_st
import pandas as pd
import numpy as np
from scipy.spatial import Delaunay
from scipy.interpolate import LinearNDInterpolator
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import ezdxf

# Cấu hình trang ứng dụng
pd_st.set_page_config(page_title="Tính Toán Thể Tích Lưới Ô Vuông (TIN)", layout="wide")
pd_st.title("📊 Ứng Dụng Tính Thể Tích Địa Hình Qua Lưới Ô Vuông (TIN)")
pd_st.caption("Ứng dụng tối ưu hóa cho môi trường PaaS - Xử lý Stateless hoàn toàn trên bộ nhớ RAM")

# Hàm đọc file tọa độ (Hỗ trợ CSV, TXT, XYZ)
def parse_coordinate_file(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        # Đọc thử file dưới dạng text
        bytes_data = uploaded_file.read()
        string_data = bytes_data.decode("utf-8")
        lines = [line.strip() for line in string_data.split('\n') if line.strip()]
        
        data = []
        for line in lines:
            # Hỗ trợ phân tách bằng dấu phẩy, dấu cách hoặc tab
            for delim in [',', '\t', ' ']:
                parts = [p.strip() for p in line.split(delim) if p.strip()]
                if len(parts) >= 3:
                    try:
                        # Lấy 3 cột đầu tiên làm X, Y, Z
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                        data.append([x, y, z])
                        break
                    except ValueError:
                        continue
        if len(data) == 0:
            return None
        return pd.DataFrame(data, columns=['X', 'Y', 'Z'])
    except Exception as e:
        pd_st.error(f"Lỗi khi đọc file {uploaded_file.name}: {str(e)}")
        return None

# Giao diện tải file
col1, col2, col3 = pd_st.columns(3)
with col1:
    file_bm1 = pd_st.file_uploader("📂 Tải lên Bề mặt 1 (Hiện trạng)", type=['txt', 'csv', 'xyz'])
with col2:
    file_bm2 = pd_st.file_uploader("📂 Tải lên Bề mặt 2 (Thiết kế/Đào đắp)", type=['txt', 'csv', 'xyz'])
with col3:
    file_boundary = pd_st.file_uploader("📂 Tải lên File Ranh giới (Tùy chọn)", type=['txt', 'csv', 'xyz'])

# Cấu hình thông số lưới vuông
grid_size = pd_st.number_input("📐 Nhập kích thước ô lưới vuông (mét):", min_value=1.0, max_value=100.0, value=10.0, step=1.0)

if file_bm1 and file_bm2:
    df_bm1 = parse_coordinate_file(file_bm1)
    df_bm2 = parse_coordinate_file(file_bm2)
    df_bound = parse_coordinate_file(file_boundary) if file_boundary else None
    
    if df_bm1 is not None and df_bm2 is not None:
        pd_st.success(" Đã đọc thành công các file bề mặt đầu vào!")
        
        # 1. Xác định ranh giới tính toán (Boundary Polygon)
        if df_bound is not None:
            bound_points = df_bound[['X', 'Y']].values
        else:
            # Nếu không có ranh giới, gộp biên bao của cả 2 file bề mặt
            combined_pts = np.vstack([df_bm1[['X', 'Y']].values, df_bm2[['X', 'Y']].values])
            hull = Delaunay(combined_pts)
            # Tạo chuỗi điểm bao ngoài cùng cơ bản bằng min/max hình hộp chữ nhật làm ranh giới mặc định
            min_x, min_y = combined_pts.min(axis=0)
            max_x, max_y = combined_pts.max(axis=0)
            bound_points = np.array([[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y], [min_x, min_y]])
            pd_st.info("⚠️ Không phát hiện file ranh giới. Hệ thống tự động thiết lập vùng bao ngoài lớn nhất làm ranh giới.")

        # 2. Xây dựng mô hình nội suy TIN tuyến tính qua Delaunay
        tri_bm1 = Delaunay(df_bm1[['X', 'Y']].values)
        interp_bm1 = LinearNDInterpolator(tri_bm1, df_bm1['Z'].values)
        
        tri_bm2 = Delaunay(df_bm2[['X', 'Y']].values)
        interp_bm2 = LinearNDInterpolator(tri_bm2, df_bm2['Z'].values)
        
        # 3. Tạo lưới ô vuông trong phạm vi ranh giới bao
        min_x_b, min_y_b = bound_points[:, 0].min(), bound_points[:, 1].min()
        max_x_b, max_y_b = bound_points[:, 0].max(), bound_points[:, 1].max()
        
        x_coords = np.arange(min_x_b + grid_size/2, max_x_b, grid_size)
        y_coords = np.arange(min_y_b + grid_size/2, max_y_b, grid_size)
        
        grid_data = []
        grid_idx = 1
        
        total_cut = 0.0
        total_fill = 0.0
        total_area = 0.0
        
        # Hàm kiểm tra điểm nằm trong đa giác ranh giới đơn giản
        def is_inside_polygon(x, y, poly):
            n = len(poly)
            inside = False
            p1x, p1y = poly[0]
            for i in range(n + 1):
                p2x, p2y = poly[i % n]
                if y > min(p1y, p2y):
                    if y <= max(p1y, p2y):
                        if x <= max(p1x, p2x):
                            if p1y != p2y:
                                xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                            if p1x == p2x or x <= xints:
                                inside = not inside
                p1x, p1y = p2x, p2y
            return inside

        for x in x_coords:
            for y in y_coords:
                # Kiểm tra xem tâm ô lưới có nằm trong ranh giới không
                if is_inside_polygon(x, y, bound_points):
                    z1 = float(interp_bm1(x, y))
                    z2 = float(interp_bm2(x, y))
                    
                    # Nếu điểm nằm ngoài vùng phủ của dữ liệu bề mặt (Nội suy ra NaN) thì bỏ qua
                    if np.isnan(z1) or np.isnan(z2):
                        continue
                    
                    delta_z = z2 - z1 # Dương là Đắp (Fill), Âm là Đào (Cut)
                    area = grid_size * grid_size
                    volume = delta_z * area
                    
                    v_cut = abs(volume) if delta_z < 0 else 0.0
                    v_fill = volume if delta_z > 0 else 0.0
                    status = "Đào" if delta_z < 0 else ("Đắp" if delta_z > 0 else "Bằng phẳng")
                    
                    grid_data.append({
                        "ID": f"G-{grid_idx:03d}",
                        "X": round(x, 2),
                        "Y": round(y, 2),
                        "Z_BM1": round(z1, 2),
                        "Z_BM2": round(z2, 2),
                        "Delta_Z": round(delta_z, 2),
                        "Area": round(area, 2),
                        "Cut": round(v_cut, 2),
                        "Fill": round(v_fill, 2),
                        "Status": status
                    })
                    
                    total_cut += v_cut
                    total_fill += v_fill
                    total_area += area
                    grid_idx += 1
                    
        df_results = pd.DataFrame(grid_data)
        
        if df_results.empty:
            pd_st.warning("⚠️ Không tìm thấy ô lưới nào khớp đồng thời phạm vi 2 bề mặt và ranh giới. Vui lòng kiểm tra lại tọa độ đầu vào.")
        else:
            # 4. Hiển thị bảng tổng hợp KPI trực quan
            st_col1, st_col2, st_col3, st_col4 = pd_st.columns(4)
            st_col1.metric("Tổng diện tích tính toán", f"{total_area:,.2f} m²")
            st_col2.metric("🟥 Tổng thể tích ĐÀO (Cut)", f"{total_cut:,.2f} m³")
            st_col3.metric("🟦 Tổng thể tích ĐẮP (Fill)", f"{total_fill:,.2f} m³")
            net_vol = total_fill - total_cut
            st_col4.metric("⚖️ Thể tích THUẦN (Net)", f"{net_vol:,.2f} m³", delta=f"{'Cần Đắp thêm' if net_vol > 0 else 'Dư đất Đào'}")
            
            # Hiển thị bảng chi tiết ô lưới thu gọn
            pd_st.subheader("📋 Bảng chi tiết kết quả ô lưới (Rút gọn hiển thị)")
            pd_st.dataframe(df_results, use_container_width=True, height=300)
            
            # 5. XỬ LÝ XUẤT FILE EXCEL MULTI-TAB TRONG BỘ NHỚ RAM
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                # Tab 1: Tổng hợp
                df_summary = pd.DataFrame([
                    ["Tên tệp bề mặt 1 (Hiện trạng)", file_bm1.name, "File"],
                    ["Tên tệp bề mặt 2 (Thiết kế)", file_bm2.name, "File"],
                    ["Tên tệp ranh giới", file_boundary.name if file_boundary else "Tự động phát sinh", "File"],
                    ["Kích thước cấu hình lưới ô vuông", f"{grid_size} x {grid_size}", "m"],
                    ["Tổng số ô lưới hợp lệ", len(df_results), "Ô"],
                    ["Diện tích vùng tính toán", total_area, "m²"],
                    ["TỔNG THỂ TÍCH ĐÀO (CUT)", total_cut, "m³"],
                    ["TỔNG THỂ TÍCH ĐẮP (FILL)", total_fill, "m³"],
                    ["THỂ TÍCH KHỐI LƯỢNG THUẦN", net_vol, "m³"]
                ], columns=["Hạng mục", "Giá trị / Thông số", "Đơn vị"])
                df_summary.to_excel(writer, sheet_name="Tổng hợp khối lượng", index=False)
                
                # Tab 2: Chi tiết ô lưới
                df_results.to_excel(writer, sheet_name="Chi tiết ô lưới", index=False)
                
            # Định dạng làm đẹp file Excel bằng openpyxl trước khi gửi download
            excel_buffer.seek(0)
            workbook = openpyxl.load_workbook(excel_buffer)
            
            # Định dạng Tab 1
            ws1 = workbook["Tổng hợp khối lượng"]
            ws1.insert_rows(1, 2)
            ws1["A1"] = "BÁO CÁO TỔNG HỢP KHỐI LƯỢNG SAN LẤP ĐỊA HÌNH"
            ws1["A1"].font = Font(name="Arial", size=16, bold=True, color="1F4E78")
            for col in range(1, 4):
                ws1.cell(row=3, column=col).font = Font(name="Arial", bold=True)
                ws1.cell(row=3, column=col).fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
            
            # Định dạng Tab 2
            ws2 = workbook["Chi tiết ô lưới"]
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(name="Arial", color="FFFFFF", bold=True)
            for col in range(1, 11):
dxf_buffer = io.StringIO()doc.write(dxf_buffer)dxf_bytes = dxf_buffer.getvalue().encode('utf-8')# 7. Nút tải file trên giao diện Webpd_st.subheader("📥 Tải Xuất Báo Cáo & Bản Vẽ")dl_col1, dl_col2 = pd_st.columns(2)with dl_col1:pd_st.download_button(label="🟢 Tải file báo cáo Excel (.xlsx)",data=styled_excel_buffer,file_name="Bao_Cao_Khoi_Luong_San_Lap.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")with dl_col2:pd_st.download_button(label="🔵 Tải bản vẽ AutoCAD (.dxf)",data=dxf_bytes,file_name="Ban_Ve_Luoi_O_Vuong_San_Lap.dxf",mime="application/dxf")else:pd_st.info("💡 Vui lòng chuẩn bị và tải lên đầy đủ hai file dữ liệu Bề mặt 1 và Bề mặt 2 ở phía trên để hệ thống bắt đầu tự động tính toán.")