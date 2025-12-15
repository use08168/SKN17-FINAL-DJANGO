document.addEventListener('DOMContentLoaded', function() {
    const logoutBtn = document.querySelector('.header-logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function() {
            window.location.href = '/logout';
        });
    }

    const settingsIcon = document.querySelector('.settings-icon');
    if (settingsIcon) {
        settingsIcon.addEventListener('click', function() {
            window.location.href = '/setting';
        });
    }
});

/* Hamburger */
function toggleSidebar() {
    document.body.classList.toggle('sidebar-open');
}

function toggleSidebarLeague() {
    const list = document.getElementById("sidebarLeagueList");
    const arrow = document.getElementById("sidebarArrow");
    
    if (list.style.display === "block") {
        list.style.display = "none";
        arrow.style.transform = "rotate(0deg)";
    } else {
        list.style.display = "block";
        arrow.style.transform = "rotate(180deg)";
    }
}

function selectSidebarLeague(league) {
    const label = document.getElementById("sidebarLabel");
    label.innerText = (league === 'TEAM_KOREA') ? 'TEAM KOREA' : 'KBO';
    
    const kboList = document.getElementById("team-list-container");
    const koreaList = document.getElementById("team-korea-list-container");

    if (league === 'TEAM_KOREA') {
        kboList.style.display = "none";   
        koreaList.style.display = "grid";    
    } else {
        kboList.style.display = "grid";    
        koreaList.style.display = "none";   
    }
    
    toggleSidebarLeague();
}

document.addEventListener('DOMContentLoaded', function() {
    const containerKBO = document.getElementById('team-list-container');
    const currentCode = containerKBO ? containerKBO.getAttribute('data-my-team') : '';
    const containerKorea = document.getElementById('team-korea-list-container');
    const label = document.getElementById("sidebarLabel");

    if (currentCode) {
        let targetBtn = document.querySelector(`.team-list-btn[data-code="${currentCode}"]`);

        if (targetBtn) {
            const isKoreaList = containerKorea.contains(targetBtn);

            if (isKoreaList) {
                if (label) label.innerText = 'TEAM KOREA';
                if (containerKBO) containerKBO.style.display = "none";
                if (containerKorea) containerKorea.style.display = "grid";
            } else {
                if (label) label.innerText = 'KBO';
                if (containerKBO) containerKBO.style.display = "grid";
                if (containerKorea) containerKorea.style.display = "none";
            }

            document.querySelectorAll('.team-list-btn').forEach(b => b.classList.remove('selected'));
            targetBtn.classList.add('selected');

            setTimeout(() => {
                targetBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 300);
        }
    }

    setInterval(checkNotifications, 5000);
});

function changeTeam(btnElement, teamCode) {
    const buttons = document.querySelectorAll('.team-list-btn');
    buttons.forEach(btn => btn.classList.remove('selected'));
    btnElement.classList.add('selected');
    location.href = "?team=" + teamCode;
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

window.addEventListener('scroll', function() {
    const header = document.getElementById('mainHeader');
    if (header) {
        window.addEventListener('scroll', function() {
            if (window.scrollY > 50) {
                header.classList.add('scrolled');
            } else {
                header.classList.remove('scrolled');
            }
        });
    }
});

function toggleHeaderSearch() {
    const wrapper = document.querySelector('.header-search-wrapper');
    const input = document.querySelector('.header-search-input');
    const form = document.getElementById('headerSearchForm');

    if (wrapper.classList.contains('active')) {
        if (input.value.trim() !== "") {
            form.submit(); 
        } else {
            wrapper.classList.remove('active');
        }
    } else {
        wrapper.classList.add('active');
        input.focus();
    }
}

document.addEventListener('click', function(e) {
    const wrapper = document.querySelector('.header-search-wrapper');
    const input = document.querySelector('.header-search-input');
    
    if (wrapper && wrapper.classList.contains('active') && !wrapper.contains(e.target) && input.value === "") {
        wrapper.classList.remove('active');
    }
});

async function checkNotifications() {
    try {
        const response = await fetch('/videos/api/check-notifications/');
        const data = await response.json();
        
        if (!data.videos || data.videos.length === 0) return;

        let notifiedList = JSON.parse(localStorage.getItem('notified_videos')) || [];
        data.videos.forEach(video => {
            const videoId = video.upload_file_id;

            if (!notifiedList.includes(videoId)) {
                showToast(`'${video.upload_title}' 분석이 완료되었습니다!`, videoId);
                notifiedList.push(videoId);
            }
        });

        localStorage.setItem('notified_videos', JSON.stringify(notifiedList));

    } catch (error) {
        console.error("알림 확인 중 오류:", error);
    }
}

function showToast(message, videoId) {
    const toast = document.getElementById('global-toast');
    const msgBox = document.getElementById('toast-message');

    msgBox.innerHTML = `${message} <br><a href="/videos/play/${videoId}/" class="toast-link">보러가기 ></a>`;

    toast.classList.add('show');
    
    setTimeout(() => {
        closeToast();
    }, 5000);
}

function closeToast() {
    const toast = document.getElementById('global-toast');
    toast.classList.remove('show');
}