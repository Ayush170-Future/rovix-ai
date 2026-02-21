from models.test_case import TestCase, Test
from typing import List, Optional

class TestCaseRepository:
    async def create(self, name: str, description: str, tests: List[Test]) -> TestCase:
        test_case = TestCase(name=name, description=description, tests=tests)
        await test_case.insert()
        return test_case
    
    async def find_by_id(self, test_case_id: str) -> Optional[TestCase]:
        return await TestCase.get(test_case_id)
    
    async def find_by_name(self, name: str) -> Optional[TestCase]:
        return await TestCase.find_one(TestCase.name == name)
    
    async def find_all(self) -> List[TestCase]:
        return await TestCase.find_all().to_list()
    
    async def update(self, test_case_id: str, updates: dict) -> TestCase:
        test_case = await TestCase.get(test_case_id)
        await test_case.set(updates)
        return test_case
    
    async def add_test(self, test_case_id: str, test: Test) -> TestCase:
        test_case = await TestCase.get(test_case_id)
        test_case.tests.append(test)
        await test_case.save()
        return test_case