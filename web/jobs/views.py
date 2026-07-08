from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from billing.models import BotApiJob

MODE_LABELS = {
    "transcribe": "Транскрибация",
    "theses": "Тезисы",
    "protocol": "Протокол",
    "translate": "Перевод",
    "custom": "Свой вариант",
}

STATUS_LABELS = {
    "pending": ("⏳ Ожидает", "secondary"),
    "processing": ("⚙️ Обрабатывается", "primary"),
    "done": ("✅ Готово", "success"),
    "error": ("❌ Ошибка", "danger"),
}


@login_required
def index(request):
    user = request.user
    jobs = []
    if user.bot_user_id:
        qs = BotApiJob.objects.filter(user_id=user.bot_user_id).order_by("-created_at")[:50]
        for job in qs:
            label, badge = STATUS_LABELS.get(job.status, (job.status, "secondary"))
            jobs.append({
                "obj": job,
                "status_label": label,
                "status_badge": badge,
                "mode_label": MODE_LABELS.get(job.mode, job.mode),
                "duration_min": round(job.duration_sec / 60, 1) if job.duration_sec else None,
            })
    return render(request, "jobs/index.html", {"jobs": jobs})
