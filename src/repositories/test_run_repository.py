from models.test_run import TestRun, TestResult
from typing import List, Optional
from datetime import datetime

class TestRunRepository:
    async def create(self, test_case_id: str, device_udid: str) -> TestRun:
        test_run = TestRun(
            test_case_id=test_case_id,
            device_udid=device_udid,
            status="queued"
        )
        await test_run.insert()
        return test_run
    
    async def find_by_id(self, test_run_id: str) -> Optional[TestRun]:
        return await TestRun.get(test_run_id)
    
    async def find_by_test_case(self, test_case_id: str) -> List[TestRun]:
        return await TestRun.find(TestRun.test_case_id == test_case_id).to_list()
    
    async def get_with_test_case(self, test_run_id: str):
        """Fetch test run with its related test case"""
        from models.test_case import TestCase
        test_run = await TestRun.get(test_run_id)
        test_case = await TestCase.get(test_run.test_case_id)
        return test_run, test_case