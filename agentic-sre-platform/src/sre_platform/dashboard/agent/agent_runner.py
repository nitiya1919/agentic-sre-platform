import json
import os
import logging
from typing import Dict, Any, List
from google import genai
from google.genai import types

from dashboard.agent.awx_tools import (
    awx_list_job_templates,
    awx_launch_job_template,
    awx_get_job_status,
    awx_get_job_stdout,
)

logger = logging.getLogger(__name__)

# Execution mapping for registered tool functions
TOOL_MAP = {
    "awx_list_job_templates": awx_list_job_templates,
    "awx_launch_job_template": awx_launch_job_template,
    "awx_get_job_status": awx_get_job_status,
    "awx_get_job_stdout": awx_get_job_stdout,
}

AWX_TOOLSET = [
    awx_list_job_templates,
    awx_launch_job_template,
    awx_get_job_status,
    awx_get_job_stdout,
]

# State-mutating tools requiring Human-in-the-Loop authorization
HIGH_RISK_TOOLS = {"awx_launch_job_template"}


def evaluate_tool_risk(function_name: str, function_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Risk assessment engine enforcing Fortified Enterprise Fleet guidelines.
    """
    if function_name in HIGH_RISK_TOOLS:
        return {
            "requires_approval": True,
            "risk_level": "HIGH",
            "reason": f"Tool '{function_name}' performs mutating operational changes on target infrastructure.",
        }
    return {
        "requires_approval": False,
        "risk_level": "LOW",
        "reason": "Read-only inspection/query tool.",
    }


class SREAgentRunner:
    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self.client = genai.Client()
        self.model_name = model_name

    def run_agent_loop(self, incident_context: str, max_turns: int = 5) -> Dict[str, Any]:
        """
        Executes multi-step ReAct agent loop for diagnosing alerts and remediating issues.
        Intercepts high-risk mutations for operator approval.
        """
        system_instruction = (
            "You are an Autonomous SRE & Infrastructure Operations Agent.\n"
            "Your objective is to diagnose system alerts, inspect playbook logs, and execute AWX templates.\n"
            "Rules:\n"
            "1. Always query and inspect relevant job templates and execution logs first.\n"
            "2. When proposing playbook execution, specify parameters explicitly.\n"
            "3. State your SRE diagnostic rationale clearly before invoking tools."
        )

        # FIXED: Removed 'model=self.model_name' from GenerateContentConfig
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=AWX_TOOLSET,
            temperature=0.1,
        )

        chat = self.client.chats.create(model=self.model_name, config=config)
        
        turn_count = 0
        agent_thoughts: List[Dict[str, Any]] = []
        
        # Initial turn
        response = chat.send_message(incident_context)

        while turn_count < max_turns:
            turn_count += 1
            
            # Check if Gemini requested tool execution
            if response.function_calls:
                tool_responses = []
                
                for call in response.function_calls:
                    func_name = call.name
                    func_args = call.args or {}
                    
                    risk_assessment = evaluate_tool_risk(func_name, func_args)
                    
                    agent_thoughts.append({
                        "turn": turn_count,
                        "action": "tool_call_requested",
                        "tool_name": func_name,
                        "tool_args": func_args,
                        "risk": risk_assessment,
                    })

                    # Intercept high-risk executions (HITL Gate)
                    if risk_assessment["requires_approval"]:
                        logger.info(f"[HITL GATE] Intercepted high-risk tool: {func_name}")
                        return {
                            "status": "PENDING_APPROVAL",
                            "agent_thoughts": agent_thoughts,
                            "pending_action": {
                                "tool_name": func_name,
                                "tool_args": func_args,
                                "risk_assessment": risk_assessment,
                            },
                            "final_response": f"High-risk action '{func_name}' intercepted. Awaiting human operator sign-off.",
                        }

                    # Execute safe read-only tools automatically
                    if func_name in TOOL_MAP:
                        logger.info(f"[AGENT] Executing low-risk tool: {func_name}")
                        tool_result_str = TOOL_MAP[func_name](**func_args)
                        
                        tool_responses.append(
                            types.Part.from_function_response(
                                name=func_name,
                                response={"result": tool_result_str}
                            )
                        )
                    else:
                        tool_responses.append(
                            types.Part.from_function_response(
                                name=func_name,
                                response={"error": f"Tool '{func_name}' not registered."}
                            )
                        )

                # Feed tool results back into Gemini chat session
                response = chat.send_message(tool_responses)
            
            else:
                # Agent completed reasoning loop
                agent_thoughts.append({
                    "turn": turn_count,
                    "action": "conclusion_reached",
                    "response": response.text,
                })
                return {
                    "status": "COMPLETED",
                    "agent_thoughts": agent_thoughts,
                    "final_response": response.text,
                }

        return {
            "status": "MAX_TURNS_EXCEEDED",
            "agent_thoughts": agent_thoughts,
            "final_response": "Agent reached maximum turn limit without resolving the incident.",
        }