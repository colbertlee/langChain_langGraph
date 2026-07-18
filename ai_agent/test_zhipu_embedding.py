"""测试智谱 AI Embedding 是否可用"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_zhipu_embedding():
    print("=" * 60)
    print("Test Zhipu AI Embedding")
    print("=" * 60)
    
    try:
        from rag import get_embedding_model
        from config import EMBEDDING_API_KEY
        
        print("\nConfig Check:")
        print("   API Key: {}...".format(EMBEDDING_API_KEY[:20]))
        print("   Model Type: zhipu")
        print("   API URL: https://open.bigmodel.cn/api/paas/v4/")
        
        print("\nInitializing Embedding model...")
        embeddings = get_embedding_model("zhipu", EMBEDDING_API_KEY)
        
        print("\nTesting vectorization...")
        test_text = "This is a test text to verify Zhipu Embedding."
        
        # Test embed_query
        result = embeddings.embed_query(test_text)
        
        print("\n[OK] Success!")
        print("   Input: {}".format(test_text))
        print("   Vector Dimension: {}".format(len(result)))
        print("   First 5 values: {}".format(result[:5]))
        
        return True
        
    except Exception as e:
        print("\n[ERROR] Test failed: {}".format(str(e)))
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_zhipu_embedding()
    sys.exit(0 if success else 1)
