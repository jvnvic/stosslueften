/*---------------------------------------------------------------------------*\
Application
    tracerFoam

Description
    Transient transport of a passive tracer C on a frozen (steady) flow field.

    Same as scalarTransportFoam, but with turbulent mixing. The diffusivity is
        D = nu/Sc + nut/Sct
    where nut is the turbulent viscosity of the steady RANS solution. The face
    fluxes phi are read from the steady solution (not recomputed from U), so
    the tracer is carried by exactly the mass-conserving simpleFoam flow.

    Written for the stosslueften project, based on scalarTransportFoam from
    OpenFOAM v2606 (www.openfoam.com), licensed GPL-3.0-or-later.
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "fvOptions.H"
#include "simpleControl.H"

int main(int argc, char *argv[])
{
    argList::addNote
    (
        "Passive tracer transport on a frozen flow field,"
        " with turbulent diffusivity nut/Sct."
    );

    #include "addCheckCaseOptions.H"
    #include "setRootCaseLists.H"
    #include "createTime.H"
    #include "createMesh.H"

    simpleControl simple(mesh);

    #include "createFields.H"

    Info<< "\nCalculating tracer transport\n" << endl;

    #include "CourantNo.H"

    while (simple.loop())
    {
        Info<< "Time = " << runTime.timeName() << nl << endl;

        while (simple.correctNonOrthogonal())
        {
            fvScalarMatrix CEqn
            (
                fvm::ddt(C)
              + fvm::div(phi, C)
              - fvm::laplacian(D, C)
             ==
                fvOptions(C)
            );

            CEqn.relax();
            fvOptions.constrain(CEqn);
            CEqn.solve();
            fvOptions.correct(C);
        }

        runTime.write();
    }

    Info<< "End\n" << endl;

    return 0;
}
