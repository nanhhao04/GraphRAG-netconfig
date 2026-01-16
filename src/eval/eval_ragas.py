import os
import json
import pandas as pd
from datetime import datetime
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
import src.connection as connection


EVAL_LOG_DIR = "log/eval"
os.makedirs(EVAL_LOG_DIR, exist_ok=True)

class NetworkRagasEvaluator:
    def __init__(self):
        self.ragas_llm = LangchainLLMWrapper(connection.llm)
        self.ragas_embeddings = LangchainEmbeddingsWrapper(connection.embeddings)

        # Định nghĩa các metrics
        self.metrics_no_ref = [faithfulness, answer_relevancy]
        self.metrics_with_ref = [context_precision, context_recall]

    def create_dataset(self, questions, answers, contexts, ground_truths=None):
        data = {
            "user_input": questions,
            "response": answers,
            "retrieved_contexts": contexts,
        }

        if ground_truths:
            data["reference"] = ground_truths

        return Dataset.from_dict(data)

    def evaluate_single_turn(self, question, answer, retrieved_context, ground_truth=None):
        print(f"Đang chấm điểm Ragas cho câu hỏi: '{question}'...")

        # Ragas yêu cầu list of lists cho context
        contexts = [retrieved_context]
        ground_truths = [ground_truth] if ground_truth else None

        dataset = self.create_dataset(
            questions=[question],
            answers=[answer],
            contexts=contexts,
            ground_truths=ground_truths
        )

        active_metrics = self.metrics_no_ref.copy()

        if ground_truth:
            active_metrics.extend(self.metrics_with_ref)
        else:
            print("Không có Ground Truth (Reference) -> Bỏ qua Context Precision & Recall.")

        try:
            results = evaluate(
                dataset=dataset,
                metrics=active_metrics,
                llm=self.ragas_llm,
                embeddings=self.ragas_embeddings
            )

            self.save_results(results)
            return results

        except Exception as e:
            print(f"Ragas Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_results(self, results):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{EVAL_LOG_DIR}/ragas_report_{timestamp}.json"

        try:
            if hasattr(results, 'to_pandas'):
                res_dict = results.to_pandas().to_dict(orient="records")[0]
            else:
                res_dict = dict(results)
        except:
            res_dict = str(results)

        print("\n" + "=" * 40)
        print("KẾT QUẢ ĐÁNH GIÁ RAGAS")
        print("=" * 40)
        if isinstance(res_dict, dict):
            for metric, score in res_dict.items():
                # Bỏ qua các cột dữ liệu thô, chỉ in điểm số
                if metric:
                #if metric not in ['user_input', 'response', 'retrieved_contexts', 'reference']:
                    print(f"- {metric}: {score}")
        print("=" * 40)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(res_dict, f, ensure_ascii=False, indent=2)
        print(f"Đã lưu report tại: {filename}")


def run_eval_pipeline(question, answer, context_list, ground_truth=None):
    evaluator = NetworkRagasEvaluator()
    return evaluator.evaluate_single_turn(question, answer, context_list, ground_truth)