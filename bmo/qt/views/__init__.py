"""QML-backed adapters for built-in feature and mode views."""

from bmo.qt.views.album import QtAlbumView
from bmo.qt.views.calendar import QtCalendarView
from bmo.qt.views.learning import QtLearningView
from bmo.qt.views.matching_game import QtMatchingGameView
from bmo.qt.views.timer import QtTimerView
from bmo.qt.views.twenty_questions import QtTwentyQuestionsView
from bmo.qt.views.weather import QtWeatherView

__all__ = [
    "QtAlbumView",
    "QtCalendarView",
    "QtLearningView",
    "QtMatchingGameView",
    "QtTimerView",
    "QtTwentyQuestionsView",
    "QtWeatherView",
]
