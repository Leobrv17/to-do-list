"""Exercise the actual shell loop with a fake Docker CLI, without a daemon."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "autoscaler" / "autoscale.sh"
FAKE_COMMAND = r'''
import json
import os
from pathlib import Path
import signal
import sys

root = Path(os.environ["MOCK_ROOT"])
frames = json.loads((root / "frames.json").read_text())
step = int((root / "step").read_text())
frame = frames[step]
command = Path(sys.argv[0]).name
args = sys.argv[1:]

if command == "sleep":
    if step + 1 == len(frames):
        os.kill(os.getppid(), signal.SIGTERM)
    else:
        (root / "step").write_text(str(step + 1))
elif command == "date":
    print(1000 + step * 10 if args == ["+%s"] else "2026-10-29T10:00:00Z")
elif command == "docker":
    with (root / "calls.jsonl").open("a") as calls:
        calls.write(json.dumps(args) + "\n")
    if args[0] == "inspect":
        print("custom-project")
    elif args[:2] == ["compose", "version"]:
        print("Docker Compose version v5.5.1")
    elif args[0] == "ps":
        if frame.get("ps_error"):
            sys.exit(1)
        for index in range(frame["replicas"]):
            print(f"{index + 1:012x}")
    elif args[0] == "stats":
        if frame.get("stats_error"):
            sys.exit(1)
        print("\n".join(frame.get("cpu", ["50%"] * frame["replicas"])))
    elif args[0] == "compose" and "up" in args:
        sys.exit(1 if frame.get("scale_error") else 0)
    else:
        raise AssertionError(args)
'''


class AutoscalerTests(unittest.TestCase):
    def run_scaler(self, frames, **config):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "frames.json").write_text(json.dumps(frames))
            (root / "step").write_text("0")
            for command in ("docker", "sleep", "date"):
                executable = root / command
                executable.write_text(f"#!{sys.executable}\n" + FAKE_COMMAND)
                executable.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "MOCK_ROOT": str(root),
                "HOSTNAME": "autoscaler-container",
                "MIN_REPLICAS": "1",
                "MAX_REPLICAS": "5",
                "CPU_SCALE_UP": "80",
                "CPU_SCALE_DOWN": "10",
                "SLEEP": "10",
                "COOLDOWN": "0",
                **{key: str(value) for key, value in config.items()},
            }
            result = subprocess.run(
                ["/bin/sh", str(SCRIPT)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            calls_file = root / "calls.jsonl"
            calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
        return result, calls

    def scale_targets(self, calls):
        return [call[call.index("--scale") + 1] for call in calls if "--scale" in call]

    def test_adds_one_replica_and_preserves_project_scope(self):
        result, calls = self.run_scaler([{"replicas": 2, "cpu": ["90%", "85%"]}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scale_targets(calls), ["backend=3"])
        scale = next(call for call in calls if "--scale" in call)
        self.assertEqual(scale[scale.index("--project-name") + 1], "custom-project")
        for option in ("--no-deps", "--no-build", "--no-recreate"):
            self.assertIn(option, scale)
        self.assertEqual(scale[-1], "backend")
        ps = next(call for call in calls if call[0] == "ps")
        self.assertIn("label=com.docker.compose.project=custom-project", ps)
        self.assertIn("label=com.docker.compose.service=backend", ps)
        self.assertIn("label=com.docker.compose.oneoff=False", ps)

    def test_removes_one_replica(self):
        result, calls = self.run_scaler([{"replicas": 3, "cpu": ["3%", "5%", "7%"]}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scale_targets(calls), ["backend=2"])

    def test_uses_average_cpu_instead_of_sum(self):
        _, calls = self.run_scaler([{"replicas": 3, "cpu": ["40%"] * 3}])
        self.assertEqual(self.scale_targets(calls), [])

    def test_obeys_minimum_and_maximum(self):
        for frame in ({"replicas": 1, "cpu": ["0%"]}, {"replicas": 5, "cpu": ["100%"] * 5}):
            with self.subTest(frame=frame):
                _, calls = self.run_scaler([frame])
                self.assertEqual(self.scale_targets(calls), [])

    def test_recovers_from_zero_instances_without_reading_host_stats(self):
        result, calls = self.run_scaler([{"replicas": 0}], MIN_REPLICAS=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scale_targets(calls), ["backend=2"])
        self.assertFalse(any(call[0] == "stats" for call in calls))

    def test_applies_maximum_even_during_cooldown(self):
        _, calls = self.run_scaler([{"replicas": 6}], COOLDOWN=60)
        self.assertEqual(self.scale_targets(calls), ["backend=5"])

    def test_ignores_unusable_measurements_and_retries(self):
        for unavailable in (
            {"replicas": 2, "cpu": ["0%"]},
            {"replicas": 2, "cpu": ["0%", "N/A"]},
            {"replicas": 2, "stats_error": True},
            {"replicas": 2, "ps_error": True},
        ):
            with self.subTest(unavailable=unavailable):
                result, calls = self.run_scaler([unavailable, {"replicas": 2, "cpu": ["90%"] * 2}])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.scale_targets(calls), ["backend=3"])

    def test_waits_on_startup_and_after_scaling(self):
        frames = [{"replicas": 1, "cpu": ["90%"]}] * 3 + [{"replicas": 2, "cpu": ["90%"] * 2}] * 2
        _, calls = self.run_scaler(frames, COOLDOWN=20)
        self.assertEqual(self.scale_targets(calls), ["backend=2", "backend=3"])

    def test_retries_failed_scaling_without_starting_cooldown(self):
        frames = [{"replicas": 1, "cpu": ["90%"], "scale_error": True}, {"replicas": 1, "cpu": ["90%"]}]
        result, calls = self.run_scaler(frames)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scale_targets(calls), ["backend=2", "backend=2"])

    def test_rejects_invalid_configuration_before_using_docker(self):
        for config in ({"MIN_REPLICAS": 0}, {"MAX_REPLICAS": 0}, {"CPU_SCALE_DOWN": 80}, {"SLEEP": 0}, {"MIN_REPLICAS": "01"}, {"COOLDOWN": "invalid"}):
            with self.subTest(config=config):
                result, calls = self.run_scaler([{"replicas": 1}], **config)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
