from __future__ import annotations

from dataclasses import dataclass

from bootloader_upgrade_tool.gui.runtime_models import *

@dataclass(frozen=True)
class FakeRequest:
    title: str = "Task"
    requirement: TaskConnectionRequirement = TaskConnectionRequirement.NONE
    cancellable: bool = True
    def create_plan(self, task_id):
        return TaskPlan(task_id, self.title, (TaskStepPlan("work", "Work", ProgressMode.INDETERMINATE),), self.requirement, self.cancellable, CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)

class FakePort:
    def __init__(self, result_factory): self.result_factory=result_factory; self.calls=[]
    def _run(self, name, task_id, request, cancellation, progress):
        self.calls.append(name)
        plan=request.create_plan(task_id)
        for step in plan.steps:
            progress(TaskProgressUpdate(task_id,step.step_id,TaskStepState.STARTED,name,"started",progress_mode=step.initial_progress_mode))
            progress(TaskProgressUpdate(task_id,step.step_id,TaskStepState.COMPLETED,name,"completed",progress_mode=step.initial_progress_mode))
        return self.result_factory(task_id, name)
    def connect(self, *args): return self._run("connect", *args)
    def disconnect(self, *args): return self._run("disconnect", *args)
    def shutdown(self, *args): return self._run("shutdown", *args)
    def execute(self, *args): return self._run("execute", *args)
