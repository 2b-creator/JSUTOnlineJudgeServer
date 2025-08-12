#include "testlib.h"
#include <string>
using namespace std;
int main(int argc, char *argv[])
{
    registerTestlibCmd(argc, argv);
    string outs = ouf.readString();
    string anss = ans.readString();
    string outscp = outs;
    outs.erase(remove(outs.begin(), outs.end(), '.'), outs.end());
    int s = outs.length();
    if (s > 10 || s < 5)
    {
        quitf(_wa, "Length error");
    }
    else
    {
        outs = outscp;
        int ge = outs[anss.size()] - '0';
        if (ge >= 5)
        {
            outs[anss.size() - 1]++;
        }
        for (int i = 0; i < anss.size(); i++)
        {
            if (anss[i] != outs[i])
            {
                quitf(_wa, "Wrong Answer");
            }
        }
        quitf(_ok, "Correct");
    }
}
