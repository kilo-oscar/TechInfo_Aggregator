import unittest

from app import (
    extract_element_technology_category,
    extract_news_category,
    extract_paper_element_category,
    extract_paper_sensor_category,
    extract_sensor_sensing_category,
)
from models import RawItem


class ElementTechnologyCategoryTests(unittest.TestCase):
    def make_item(self, source_name: str, title: str) -> RawItem:
        return RawItem(source_type="news", source_name=source_name, title=title)

    def test_sensing_source_is_classified_as_sensing(self):
        item = self.make_item("Google News / Robotics Sensing", "Robot vision system")
        self.assertEqual(extract_element_technology_category(item), "センサ・センシング")

    def test_component_titles_are_classified_by_component_type(self):
        source = "Google News / Robotics Components"
        self.assertEqual(extract_element_technology_category(self.make_item(source, "Direct drive motor for robots")), "ダイレクトドライブモータ")
        self.assertEqual(extract_element_technology_category(self.make_item(source, "Harmonic drive robot reducer")), "ギヤ・減速機")
        self.assertEqual(extract_element_technology_category(self.make_item(source, "New robot actuator")), "アクチュエータ")
        self.assertEqual(extract_element_technology_category(self.make_item(source, "Robot tactile sensor")), "センサ・センシング")

    def test_sensor_sensing_articles_are_classified_by_modality(self):
        source = "Google News / Robotics Sensing"
        self.assertEqual(extract_sensor_sensing_category(self.make_item(source, "Robot vision camera")), "視覚センサ・カメラ")
        self.assertEqual(extract_sensor_sensing_category(self.make_item(source, "Robot auditory sensing")), "聴覚センサ")
        self.assertEqual(extract_sensor_sensing_category(self.make_item(source, "Force-torque tactile sensor")), "力触覚センサ")

    def test_real_haptics_is_grouped_with_force_tactile_sensors(self):
        item = self.make_item("Google News / Real Haptics", "Haptic teleoperation technology")
        self.assertEqual(extract_news_category(item), "要素技術")
        self.assertEqual(extract_element_technology_category(item), "センサ・センシング")
        self.assertEqual(extract_sensor_sensing_category(item), "力触覚センサ")

    def test_author_name_does_not_make_paper_an_audio_sensor(self):
        item = RawItem(
            source_type="paper",
            source_name="arXiv",
            title="Iterated Invariant EKF for Quadruped Robot Odometry",
            raw_summary="A proprioceptive state estimation method for legged robots.",
            raw_text="Authors: Claudio Semini",
        )
        self.assertEqual(extract_paper_element_category(item), "")
        self.assertEqual(extract_paper_sensor_category(item), "")

    def test_haptic_teleoperation_is_a_force_tactile_paper(self):
        item = RawItem(
            source_type="paper",
            source_name="arXiv",
            title="Keeping the Franka Emika Panda alive",
            raw_summary="A ROS 2 stack validated for haptic teleoperation and compliance control.",
        )
        self.assertEqual(extract_paper_element_category(item), "センサ・センシング")
        self.assertEqual(extract_paper_sensor_category(item), "力触覚センサ")

    def test_explicit_force_torque_sensor_paper_is_force_tactile(self):
        item = RawItem(
            source_type="paper",
            source_name="arXiv",
            title="A force-torque sensor for robot manipulation",
        )
        self.assertEqual(extract_paper_element_category(item), "センサ・センシング")
        self.assertEqual(extract_paper_sensor_category(item), "力触覚センサ")


if __name__ == "__main__":
    unittest.main()
