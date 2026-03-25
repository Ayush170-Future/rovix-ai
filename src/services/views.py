from pydantic import BaseModel, Field
from typing import Literal, List

from tools.todo_management import TODO_WRITE_INPUT_DESCRIPTION


class Action(BaseModel):
    action_type: Literal["key_press", "click", "swipe", "multi_swipe", "wait", "todo_write"] = Field(
        description="Represents the type of action to be performed. This can be a key press, click on a coordinate, swipe, multi-point swipe, wait, or todo_write for managing task lists."
    )
    x: int | None = Field(
        default=None,
        description="X-coordinate on the screen. Required for 'click' action. For 'swipe' action, this is the starting X-coordinate. Not used for 'multi_swipe' or 'todo_write'."
    )
    y: int | None = Field(
        default=None,
        description="Y-coordinate on the screen. Required for 'click' action. For 'swipe' action, this is the starting Y-coordinate. Not used for 'multi_swipe' or 'todo_write'."
    )
    end_x: int | None = Field(
        default=None,
        description="Ending X-coordinate for 'swipe' action. Required only for 'swipe'. Not used for 'multi_swipe' or 'todo_write'."
    )
    end_y: int | None = Field(
        default=None,
        description="Ending Y-coordinate for 'swipe' action. Required only for 'swipe'. Not used for 'multi_swipe' or 'todo_write'."
    )
    waypoints: List[List[int]] | None = Field(
        default=None,
        description="List of (x, y) coordinate tuples for 'multi_swipe' action ONLY. The gesture will follow this path smoothly from first point to last. Includes start, middle, and end points. Example: [(100, 100), (200, 150), (300, 100)] creates a curved path starting at (100,100) and ending at (300,100). Required for 'multi_swipe', ignored for other actions."
    )
    key_name: str | None = Field(
        default=None,
        description="Name of the keyboard key to press. All possible keys are listed in the last message. Required only for 'key_press' action."
    )
    duration: float = Field(
        default=0.1,
        description="Duration of the action in seconds. For 'click': hold duration (0.1 = quick tap). For 'swipe': time to complete the swipe. For 'multi_swipe': total time for entire path. For 'wait': how long to wait. Not used for 'todo_write'. Default: 0.1s."
    )
    todo_input: str | None = Field(
        default=None,
        description=TODO_WRITE_INPUT_DESCRIPTION
    )


class TestResult(BaseModel):
    test_case_id: str = Field(
        description="The id of the test case that you are reporting the result for."
    )
    completion: bool = Field(
        description="True if you were able to complete the test case successfully, false if you failed to achieve the condition required to run the test case."
    )
    failure_reason: str = Field(
        description="If completion is false, provide a brief explanation of why you failed to complete the test case. Otherwise NA."
    )
    virdict: Literal["pass", "fail"] = Field(
        description="Pass if the actual outcome matches the expected outcome, fail if it does not."
    )
    comment: str = Field(
        description="Free field to comment on the test case. You can use this to provide information about how the actual outcome differed from the expected outcome."
    )


class AgentOutput(BaseModel):
    """Structured output produced by the agent for each decision step."""

    game_state_summary: str = Field(
        description="A concise summary of the current game state, key observations, and important context that should be remembered for future steps. This summary will be preserved in the conversation history even when screenshots are removed. Include: current game situation, player status, important objects/entities, recent changes, and any critical information needed for decision-making. Max 100 words."
    )
    reason: str = Field(
        description="Use this field to reason about the current game state and your overall performance, observations, goals that will help you complete the game and figure out the next set of actions. Max 100 words."
    )
    end_game: bool = Field(
        default=False,
        description="This represents whether the game has ended or not. If the game has ended, the player should not take any action."
    )
    force_annotate: bool = Field(
        default=False,
        description="Set to true if you believe the cached UI annotation is stale and a fresh vision scan is needed. This is a top-level boolean flag — do NOT add any action to the actions list for this. Simply set this field to true and leave actions empty."
    )
    actions: List[Action] = Field(
        default_factory=list,
        description="A list of actions to be executed sequentially. This can be a combination of keyboard and button press actions."
    )
    test_results: List[TestResult] = Field(
        default_factory=list,
        description="List of test results. You are not expected to fill this always. Only fill it when you have executed atleast one test case and have a result to report otherwise keep it empty."
    )


class GamePauseEvent(BaseModel):
    current_step: int
    current_frame: int
