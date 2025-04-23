document.getElementById('gen-form').onsubmit = function(e) {
    e.preventDefault();
    const form = e.target;
    const data = new FormData(form);
    const task_id = Date.now().toString();
    data.append('task_id', task_id);
    const outputFormat = form.output_format.value;
    data.append('output_format', outputFormat);
    const numVariations = form.num_variations.value;
    data.append('num_variations', numVariations);
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-bar').innerText = '0%';
    document.getElementById('progress-text').innerText = 'Đang tải lên và bắt đầu xử lý...';
    showDownloadLinks(task_id, outputFormat, false);
    fetch('/process', {
        method: 'POST',
        body: data
    })
    .then(res => res.json())
    .then(resp => {
        if (resp.error) {
            document.getElementById('progress-bar').style.width = '0%';
            document.getElementById('progress-bar').innerText = '';
            document.getElementById('progress-text').innerText = '';
            document.getElementById('result').innerText = resp.error;
        } else {
            pollProgress(task_id, outputFormat);
        }
    })
    .catch(() => {
        document.getElementById('progress-bar').style.width = '0%';
        document.getElementById('progress-bar').innerText = '';
        document.getElementById('progress-text').innerText = '';
        document.getElementById('result').innerText = 'Có lỗi xảy ra!';
    });
};

// Hàm kiểm tra tiến trình và hiện popup khi gặp waiting_user
function pollProgress(task_id, outputFormat) {
    fetch(`/progress/${task_id}`)
      .then(res => res.json())
      .then(info => {
        if (info.waiting_user) {
          if (confirm("AI gặp khó khăn khi sinh đủ biến thể. Bạn muốn thử tiếp không? (OK: Thử tiếp, Cancel: Bỏ qua)")) {
            fetch('/user_decision', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({task_id: task_id, decision: 'retry'})
            });
          } else {
            fetch('/user_decision', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({task_id: task_id, decision: 'skip'})
            });
          }
          setTimeout(() => pollProgress(task_id, outputFormat), 2000);
          return;
        }
        // Nếu không waiting_user thì dùng logic cũ để cập nhật tiến trình
        if (info.error) {
            document.getElementById('progress-text').innerText = '⛔ Đã xảy ra lỗi!';
            document.getElementById('result').innerHTML = `<span style="color: red; font-weight: bold;">Lỗi: ${info.error}</span>`;
            return; // Dừng kiểm tra tiến trình
        }

        if (info.done) {
            document.getElementById('progress-bar').style.width = '100%';
            document.getElementById('progress-bar').innerText = '✅ 100%';
            document.getElementById('progress-text').innerText = 'Xử lý thành công!';
            // Kiểm tra key output/output_xlsx trước khi hiển thị link
            if ((outputFormat === 'xlsx' && info.output_xlsx) || (outputFormat !== 'xlsx' && info.output)) {
                showDownloadLinks(task_id, outputFormat, true);
            } else {
                document.getElementById('result').innerHTML = '<span style="color: red; font-weight: bold;">Không tìm thấy file kết quả để tải về!</span>';
            }
        } else if (info.current != null && info.total != null && info.total > 0) {
            const percent = Math.round(info.current / info.total * 100);
            updateProgressBar(percent);
            document.getElementById('progress-text').innerText = `Đang xử lý ${info.current}/${info.total}...`;
            showDownloadLinks(task_id, outputFormat, false);
            setTimeout(() => pollProgress(task_id, outputFormat), 1000);
        } else {
            // Trạng thái chờ ban đầu hoặc không xác định
            document.getElementById('progress-bar').style.width = '0%';
            document.getElementById('progress-bar').innerText = '0%';
            document.getElementById('progress-text').innerText = 'Đang chờ xử lý...';
             // Hiển thị link nhưng ở trạng thái chờ (disabled)
            showDownloadLinks(task_id, outputFormat, false);
            setTimeout(() => pollProgress(task_id, outputFormat), 1000); // Vẫn tiếp tục kiểm tra
        }
      })
      .catch(err => {
        console.error("Lỗi khi fetch progress:", err);
        document.getElementById('progress-text').innerText = 'Lỗi kết nối hoặc xử lý!';
        document.getElementById('result').innerHTML = `<span style="color: red; font-weight: bold;">Không thể kiểm tra tiến trình: ${err.message}.</span>`;
      });
}

// --- Đã xoá hiệu ứng tên lửa, trả lại updateProgressBar như cũ ---
function updateProgressBar(percent) {
    document.getElementById('progress-bar').style.width = percent + '%';
    document.getElementById('progress-bar').innerText = percent + '%';
}

function showDownloadLinks(task_id, outputFormat, enabled) {
    let linkHtml = '';
    let disabledClass = enabled ? '' : ' disabled';
    let style = enabled ? '' : ' style="pointer-events:none;opacity:0.5;"';
    let linkText = outputFormat === 'xlsx' ? 'Tải xuống XLSX' : 'Tải xuống CSV';
    if (enabled) {
        if (outputFormat === 'xlsx') {
            linkHtml = `<a id="download-link"${disabledClass} href="/download_xlsx/${task_id}"${style}>${linkText}</a>`;
        } else {
            linkHtml = `<a id="download-link"${disabledClass} href="/download/${task_id}"${style}>${linkText}</a>`;
        }
        document.getElementById('result').innerHTML = linkHtml;
        document.getElementById('result').style.display = 'block';
    } else {
        // Khi chưa xong thì ẩn nút tải về
        document.getElementById('result').innerHTML = '';
        document.getElementById('result').style.display = 'none';
    }
}

// --- Đã xóa chức năng chuyển theme và nút theme-toggle-btn ---
// Đã xóa setTheme, toggleTheme, sự kiện DOMContentLoaded liên quan theme, và đoạn tạo nút theme-toggle-btn