import streamlit as st
import pandas as pd
import numpy as np
from scipy.spatial import Delaunay, ConvexHull
from scipy.interpolate import LinearNDInterpolator
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
import ezdxf

# 1. Cấu hình giao diện Web App
st.set_page_config(page_title="Tính Toán Thể Tích Lưới Ô Vuông (TIN)", layout="wide")
st.title("📊 Ứng Dụng Tính Thể Tích Địa Hình Qua Lưới Ô Vuông (TIN)")
st.caption("Phiên bản tối ưu cho PaaS - Hỗ trợ tệp XYZ/CSV/TXT/DXF, cao độ cố định và Chu vi Convex Hull")

# 2. Hàm đọc dữ liệu từ file DXF bản vẽ AutoCAD
def parse_dxf_surface(uploaded_file):
    try:
        # Đọc luồng dữ liệu bytes từ file upload
        bytes_data = uploaded_file.read()
        doc = ezdxf.readbytes(bytes_data)
        msp = doc.modelspace()
        points = []
        
        # Đọc dữ liệu từ thực thể POINT
        for entity in msp.query('POINT'):
            points.append(entity.dxf.location)
            
        # Đọc dữ liệu từ thực thể LINE
        for entity in msp.query('LINE'):
            points.append(entity.dxf.start)
            points.append(entity.dxf.end)
            
        # Đọc dữ liệu từ thực thể 3DFACE
        for entity in msp.query('3DFACE'):
            for i in range(4):
                points.append(entity.get_vertex(i))
                
        # Đọc dữ liệu từ đường đa tuyến POLYLINE / LWPOLYLINE
        for entity in msp.query('LWPOLYLINE POLYLINE'):
            for vertex in entity.vertices():
                # Nếu đường 2D không có cao độ, sử dụng cao độ mặc định của layer
                z = entity.dxf.elevation if hasattr(entity.dxf, 'elevation') else 0.0
                if len(vertex) >= 3:
                    points.append((vertex[0], vertex[1], vertex[2]))
                else:
                    points.append((vertex[0], vertex[1], z))
                    
        if not points:
            return None
            
        df = pd.DataFrame(points, columns=['X', 'Y', 'Z'])
        return df.drop_duplicates(subset=['X', 'Y']).reset_index(drop=True)
    except Exception as e:
        st.error(f"Lỗi khi giải mã file DXF: {str(e)}")
        return None

# 3. Hàm đọc dữ liệu từ file văn bản tọa độ (TXT, CSV, XYZ)
def parse_text_surface(uploaded_file):
    try:
        bytes_data = uploaded_file.read()
        string_data = bytes_data.decode("utf-8")
        lines = [line.strip() for line in string_data.split('\n') if line.strip()]
        data = []
        for line in lines:
            for delim in [',', '\t', ' ']:
                parts = [p.strip() for p in line.split(delim) if p.strip()]
                if len(parts) >= 3:
                    try:
                        x = float(parts[0])
                        y = float(parts[1])
                        z = float(parts[2])
                        data.append([x, y, z])
                        break
                    except (ValueError, IndexError):
                        continue
        if len(data) == 0:
            return None
        return pd.DataFrame(data, columns=['X', 'Y', 'Z'])
    except Exception as e:
        st.error(f"Lỗi khi giải mã file văn bản: {str(e)}")
        return None

# 4. Hàm tổng hợp xử lý file ranh giới (Hỗ trợ cả TXT và DXF)
def parse_boundary(uploaded_file):
    if uploaded_file is None:
        return None
    name = uploaded_file.name.lower()
    if name.endswith('.dxf'):
        try:
            doc = ezdxf.readbytes(uploaded_file.read())
            msp = doc.modelspace()
            for entity in msp.query('LWPOLYLINE POLYLINE'):
                pts = [(v[0], v[1]) for v in entity.vertices()]
                if len(pts) >= 3:
                    return np.array(pts)
            return None
        except Exception:
            return None
    else:
        df = parse_text_surface(uploaded_file)
        if df is not None:
            return df[['X', 'Y']].values
        return None

# 5. Thuật toán kiểm tra điểm nằm trong đa giác kín (Ray-casting)
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

# 6. Giao diện cấu hình nhập dữ liệu đầu vào
st.subheader("🛠️ Cấu hình dữ liệu Bề mặt 1 (Hiện trạng)")
type_bm1 = st.radio("Chọn hình thức nhập Bề mặt 1:", ["Tải file (XYZ/TXT/CSV/DXF)", "Nhập giá trị cao độ mặt phẳng cố định"], key="t1")
df_bm1 = None
if type_bm1 == "Tải file (XYZ/TXT/CSV/DXF)":
    file_bm1 = st.file_uploader("📂 Tải lên file Bề mặt 1", type=['txt', 'csv', 'xyz', 'dxf'], key="f1")
    if file_bm1:
        df_bm1 = parse_dxf_surface(file_bm1) if file_bm1.name.lower().endswith('.dxf') else parse_text_surface(file_bm1)
else:
    const_z1 = st.number_input("✏️ Nhập cao độ cố định cho Bề mặt 1 (m):", value=0.0, key="z1")

st.subheader("🛠️ Cấu hình dữ liệu Bề mặt 2 (Thiết kế / Đào đắp)")
type_bm2 = st.radio("Chọn hình thức nhập Bề mặt 2:", ["Tải file (XYZ/TXT/CSV/DXF)", "Nhập giá trị cao độ mặt phẳng cố định"], key="t2")
df_bm2 = None
if type_bm2 == "Tải file (XYZ/TXT/CSV/DXF)":
    file_bm2 = st.file_uploader("📂 Tải lên file Bề mặt 2", type=['txt', 'csv', 'xyz', 'dxf'], key="f2")
    if file_bm2:
        df_bm2 = parse_dxf_surface(file_bm2) if file_bm2.name.lower().endswith('.dxf') else parse_text_surface(file_bm2)
else:
    const_z2 = st.number_input("✏️ Nhập cao độ cố định cho Bề mặt 2 (m):", value=0.0, key="z2")

st.subheader("🧱 Cấu hình Ranh giới tính toán")
file_boundary = st.file_uploader("📂 Tải lên file Ranh giới (Tùy chọn: DXF, TXT, CSV, XYZ)", type=['txt', 'csv', 'xyz', 'dxf'], key="fb")

grid_size = st.number_input("📐 Nhập kích thước ô lưới vuông (mét):", min_value=1.0, max_value=100.0, value=10.0, step=1.0)

# Khởi tạo cờ kiểm tra dữ liệu đã hợp lệ để tính chưa
ready_to_compute = False
if type_bm1 == "Tải file (XYZ/TXT/CSV/DXF)" and df_bm1 is None:
    pass
elif type_bm2 == "Tải file (XYZ/TXT/CSV/DXF)" and df_bm2 is None:
    pass
else:
    ready_to_compute = True

# 7. Tiến trình tính toán chính
if ready_to_compute and (type_bm1 == "Tải file (XYZ/TXT/CSV/DXF)" or type_bm2 == "Tải file (XYZ/TXT/CSV/DXF)"):
    st.success("✔️ Hệ thống đã sẵn sàng tính toán dữ liệu!")
    
    # Gom toàn bộ các điểm thực tế để tìm chu vi ngoài nếu cần
    all_points_list = []
    if df_bm1 is not None:
        all_points_list.append(df_bm1[['X', 'Y']].values)
    if df_bm2 is not None:
        all_points_list.append(df_bm2[['X', 'Y']].values)
    combined_pts = np.vstack(all_points_list)
    
    # Xác lập ranh giới (Trường hợp 1 hoặc Trường hợp 2 Convex Hull)
    df_bound_pts = parse_boundary(file_boundary) if file_boundary else None
    if df_bound_pts is not None:
        bound_points = df_bound_pts
        st.info("ℹ️ Sử dụng ranh giới được tải lên từ file.")
    else:
        # Áp dụng thuật toán Convex Hull tính chu vi ngoài khít nhất cho bề mặt
        hull = ConvexHull(combined_pts)
        bound_points = combined_pts[hull.vertices]
        # Khép góc đường bao chu vi
        bound_points = np.vstack([bound_points, bound_points[0]])
        st.info(" Chu vi bề mặt ngoài cùng đã tự động được tính toán làm đường ranh giới bằng thuật toán Convex Hull.")

    # Xây dựng các hàm nội suy TIN cơ sở
    if df_bm1 is not None:
        tri_bm1 = Delaunay(df_bm1[['X', 'Y']].values)
        interp_bm1 = LinearNDInterpolator(tri_bm1, df_bm1['Z'].values)
    else:
        interp_bm1 = lambda x, y: const_z1
        
    if df_bm2 is not None:
        tri_bm2 = Delaunay(df_bm2[['X', 'Y']].values)
        interp_bm2 = LinearNDInterpolator(tri_bm2, df_bm2['Z'].values)
    else:
        interp_bm2 = lambda x, y: const_z2

    # Sinh ma trận lưới ô vuông trong phạm vi hộp bao ranh giới
    min_x_b, min_y_b = bound_points[:, 0].min(), bound_points[:, 1].min()
    max_x_b, max_y_b = bound_points[:, 0].max(), bound_points[:, 1].max()
    
    x_coords = np.arange(min_x_b + grid_size/2, max_x_b, grid_size)
    y_coords = np.arange(min_y_b + grid_size/2, max_y_b, grid_size)
    
    grid_data = []
    grid_idx = 1
    total_cut, total_fill, total_area = 0.0, 0.0, 0.0
    
    for x in x_coords:
        for y in y_coords:
            if is_inside_polygon(x, y, bound_points):
                z1 = float(interp_bm1(x, y))
                z2 = float(interp_bm2(x, y))
                
                if np.isnan(z1) or np.isnan(z2):
                    continue
                
                delta_z = z2 - z1
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
(x_c + half_g, y_c + half_g),(x_c - half_g, y_c + half_g),(x_c - half_g, y_c - half_g)]for i in range(4):msp.add_line(pts[i], pts[i+1], dxfattribs={'layer': 'GRID_LINE'})msp.add_text(row_data['ID'], dxfattribs={'layer': 'TEXT_ID', 'height': grid_size * 0.1}).set_placement((x_c - half_g + 0.5, y_c + half_g - (grid_size * 0.15)))vol_color = 1 if row_data['Status'] == "Đào" else 5vol_str = f"C: {row_data['Cut']}" if row_data['Status'] == "Đào" else f"F: {row_data['Fill']}"msp.add_text(vol_str, dxfattribs={'layer': 'TEXT_VOLUME', 'height': grid_size * 0.12, 'color': vol_color}).set_placement((x_c - half_g + 0.5, y_c - half_g + 0.5))dxf_buffer = io.StringIO()doc.write(dxf_buffer)dxf_bytes = dxf_buffer.getvalue().encode('utf-8')# 11. Các nút bấm Download dữ liệu cho kỹ sưst.subheader("📥 Tải Xuất Kết Quả")dl_col1, dl_col2 = st.columns(2)with dl_col1:st.download_button(label="🟢 Tải file báo cáo Excel (.xlsx)",data=styled_excel_buffer,file_name="Bao_Cao_San_Lap_TIN.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")with dl_col2:st.download_button(label="🔵 Tải bản vẽ AutoCAD (.dxf)",data=dxf_bytes,file_name="Ban_Ve_Luoi_O_Vuong.dxf",mime="application/dxf")else:st.info("💡 Vui lòng thiết lập cấu hình thông số / tải tệp cho Bề mặt 1 và Bề mặt 2 ở trên để hệ thống tiến hành tính toán.")